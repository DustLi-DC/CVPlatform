"""采集任务的创建、后台执行、进度统计、重试与重启恢复。

设计依据：开发设计与验收.md 第 7.4 节，以及阶段 6 任务第 3、4、5 条。

关键约定：
- **单实例、低并发**：进程内一个后台线程顺序处理任务，网络请求走全局限速器；
- **不在网络请求期间持有写事务**：每处理一条明细就提交一次，逐条落库，
  因此中断点由明细表本身决定，续跑不会重复处理已成功的条目；
- **计数来自明细状态的实际统计**，不使用逐步累加的中间值；
- 服务重启时把「运行中」的任务收敛为「interrupted」，未完成明细退回「pending」，
  再按 AUTO_RESUME_TASKS 决定是否自动续跑。
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func
from sqlmodel import Session, col, select

from ..models.entities import CollectionTask, CollectionTaskItem, Paper
from .collector import lookup
from .index_cache import IndexCache, shared_cache
from .keyword_job import process_pending
from .papers import ApiError, find_existing_paper, save_paper

logger = logging.getLogger("cvplatform.tasks")

ITEM_STATUSES = ("pending", "running", "success", "duplicate", "failed")
# 只有运行中/待处理属于非终态；其余为终态
NON_TERMINAL_TASK_STATUSES = ("pending", "running", "interrupted")
# 索引匹配的最低相似度（与索引缓存保持一致）
AUTO_ACCEPT_SCORE = 0.86


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


AUTO_RESUME_TASKS = _env_flag("AUTO_RESUME_TASKS", True)


# ------------------------------------------------------------------ 计数


def refresh_counts(session: Session, task: CollectionTask) -> CollectionTask:
    """按明细表的实际状态重算任务计数。"""
    rows = session.exec(
        select(CollectionTaskItem.status, func.count())
        .where(CollectionTaskItem.task_id == task.id)
        .group_by(CollectionTaskItem.status)
    ).all()
    counts = {status: int(number) for status, number in rows}
    task.pending_count = counts.get("pending", 0)
    task.running_count = counts.get("running", 0)
    task.success_count = counts.get("success", 0)
    task.duplicate_count = counts.get("duplicate", 0)
    task.failed_count = counts.get("failed", 0)
    task.total_count = sum(counts.values()) if counts else task.total_count
    session.add(task)
    return task


def _settle_status(task: CollectionTask) -> str:
    """根据计数决定任务状态：全部成功、部分成功、全部失败。"""
    if task.pending_count or task.running_count:
        return "running"
    finished = task.success_count + task.duplicate_count + task.failed_count
    if finished == 0:
        return "failed"
    if task.failed_count == 0:
        return "success"
    if task.success_count == 0 and task.duplicate_count == 0:
        return "failed"
    return "partial"


# ------------------------------------------------------------------ 创建


@dataclass
class TaskCreation:
    task_id: int
    total_count: int


def create_batch_task(
    session: Session,
    *,
    file_name: str,
    file_size: int | None,
    file_format: str,
    rows: list[tuple[int, str, str | None, int | None]],
) -> CollectionTask:
    """创建批量导入任务与明细。rows 为 (行号, 标题, 会议, 年份)。"""
    task = CollectionTask(
        kind="batch",
        file_name=file_name,
        file_size=file_size,
        file_format=file_format,
        total_count=len(rows),
        pending_count=len(rows),
        status="pending",
        message="任务已创建，等待处理。",
        created_at=_now(),
    )
    session.add(task)
    session.flush()

    for line_no, title, conference, year in rows:
        session.add(
            CollectionTaskItem(
                task_id=task.id or 0,
                line_no=line_no,
                input_title=title,
                input_conference=conference,
                input_year=year,
                status="pending",
                created_at=_now(),
                updated_at=_now(),
            )
        )
    session.flush()
    refresh_counts(session, task)
    return task


def create_harvest_task(
    session: Session,
    *,
    conference: str,
    year: int,
    stride: int,
    limit: int,
    titles: list[tuple[int, str]],
) -> CollectionTask:
    """创建真实数据采集任务（kind=harvest），记录抽样步长以便复现。"""
    task = CollectionTask(
        kind="harvest",
        file_name=f"{conference}{year}_sample",
        file_format="index",
        sample_stride=stride,
        sample_limit=limit,
        total_count=len(titles),
        pending_count=len(titles),
        status="pending",
        message=f"{conference} {year} 抽样采集：步长 {stride}，目标 {limit} 条。",
        created_at=_now(),
    )
    session.add(task)
    session.flush()
    for index, (_, title) in enumerate(titles, start=1):
        session.add(
            CollectionTaskItem(
                task_id=task.id or 0,
                line_no=index,
                input_title=title,
                input_conference=conference,
                input_year=year,
                status="pending",
                created_at=_now(),
                updated_at=_now(),
            )
        )
    session.flush()
    refresh_counts(session, task)
    return task


# ------------------------------------------------------------------ 单条处理


def _progress(message: str) -> None:
    """进度日志：写入应用日志，便于运维观察长时间任务。"""
    logger.info("任务进度：%s", message)


def _finish_item(
    item_id: int,
    *,
    status: str,
    message: str | None = None,
    paper_id: int | None = None,
    duplicate_of: int | None = None,
) -> str:
    """在独立短事务里写入明细终态。"""
    from ..db.engine import session_scope

    with session_scope() as session:
        item = session.get(CollectionTaskItem, item_id)
        if item is None:
            return status
        item.status = status
        item.message = message
        if paper_id is not None:
            item.paper_id = paper_id
        if duplicate_of is not None:
            item.duplicate_of_paper_id = duplicate_of
        item.updated_at = _now()
        session.add(item)
    return status


def process_item(item_id: int, *, cache) -> str:
    """处理一条明细，返回终态。

    事务边界刻意切得很短：**网络请求期间不持有任何写事务**。
    每个数据库步骤各自开一个短事务并立即提交，因此中断点由明细状态决定，
    续跑时不会重复处理已成功的条目，也不会因为长时间挂起而阻塞其他写入。
    """
    from ..db.engine import session_scope

    # 步骤 1：取出输入并标记为处理中（短事务）
    with session_scope() as session:
        item = session.get(CollectionTaskItem, item_id)
        if item is None:
            return "failed"
        title = item.input_title
        conference = item.input_conference
        year = item.input_year
        item.status = "running"
        item.attempts += 1
        item.updated_at = _now()
        session.add(item)

    # 步骤 2：本地已存在则记为重复（短事务，只读）
    # 用精确匹配（会议年份 + 去重键，或标题全等），避免把标题相近的独立论文误判为重复
    with session_scope() as session:
        existing = find_existing_paper(
            session, title=title, conference=conference, year=year
        )
        existing_id = existing.id if existing else None
        existing_code = existing.code if existing else None
    if existing_id is not None:
        return _finish_item(
            item_id,
            status="duplicate",
            message=f"重复：已存在于论文库（{existing_code}），已跳过",
            paper_id=existing_id,
            duplicate_of=existing_id,
        )

    # 步骤 3：确定会议年份并定位详情页。可能需要访问网络，此时不持有事务
    paper_path: str | None = None
    if conference and year:
        # 会议年份已知：只需确保该组合的索引已载入，再按题目定位详情页。
        # 这里必须显式载入：不能假设索引已被预先加载（换一个进程就会有缓存为空）
        try:
            cache.load(conference, year, timeout=30.0)
        except Exception as error:  # noqa: BLE001 - 索引不可用时按未找到处理
            _progress(f"{conference} {year} 索引载入失败：{error}")
        hit, score = cache.match(title, conference=conference, year=year)
        if hit is not None and score < 1.0:
            # 模糊命中不自动入库：批量任务无人盯着，宁可让人确认一次
            return _finish_item(
                item_id,
                status="failed",
                message=(
                    f"在 {conference} {year} 索引中找到相近条目《{hit.title}》"
                    f"（相似度 {score:.2f}）但不是完全一致，需人工确认后导入。"
                ),
            )
        paper_path = hit.paper_path if hit else None
    else:
        # 会议年份未知：先把目标组合的索引都载入，再按题目匹配
        try:
            cache.load_all(timeout=30.0)
        except Exception as error:  # noqa: BLE001 - 索引不可用时退回在线检索
            _progress(f"索引载入失败，改用在线检索：{error}")
        hit, score = cache.match(title)
        if hit is not None:
            conference, year, paper_path = hit.conference, hit.year, hit.paper_path
        elif score and score < AUTO_ACCEPT_SCORE:
            return _finish_item(
                item_id,
                status="failed",
                message=(
                    f"在会议索引中未找到足够接近的题目（最高相似度 {score:.2f}），"
                    "请确认题目是否为会议论文页原文，或改用单篇采集人工确认。"
                ),
            )

    # 步骤 4：仍无法确定会议年份时退回在线检索，交由单篇采集人工确认
    if not (conference and year):
        with session_scope() as session:
            outcome = lookup(session, title, conference=conference, year=year)
        if outcome.outcome == "remote_candidates":
            best = outcome.candidates[0]
            return _finish_item(
                item_id,
                status="failed",
                message=(
                    f"找到 {len(outcome.candidates)} 条在线候选（最高相似度 "
                    f"{best.match_score:.2f}），但无法确定会议年份，"
                    "请在单篇采集中确认后导入。"
                ),
            )
        if outcome.outcome == "remote_empty":
            return _finish_item(
                item_id, status="failed", message="本地与在线来源都没有找到匹配的论文。"
            )
        return _finish_item(
            item_id,
            status="failed",
            message=outcome.message or "在线来源暂时不可用，可稍后重试。",
        )

    if paper_path is None:
        return _finish_item(
            item_id,
            status="failed",
            message=f"在 {conference} {year} 索引中未找到对应条目，无法取得摘要与原文链接。",
        )

    # 步骤 5：取详情页（网络请求，不持有事务）
    from .collector import _index_module

    module = _index_module(conference)
    try:
        fields = module.fetch_paper(paper_path, timeout=30.0, retries=1)
    except ApiError as error:
        return _finish_item(item_id, status="failed", message=error.message)
    except Exception as error:  # noqa: BLE001 - 单条失败不中断整批
        logger.exception("详情页获取失败：item=%s", item_id)
        return _finish_item(
            item_id, status="failed", message=f"详情页获取失败：{type(error).__name__}"
        )

    # 步骤 6：写库（短事务）：保存论文与写入明细终态
    try:
        with session_scope() as session:
            paper, created = save_paper(
                session,
                title=fields.title or title,
                conference=conference,
                year=year,
                abstract=fields.abstract,
                author_keywords=[],
                landing_url=fields.landing_url,
                pdf_url=fields.pdf_url,
                primary_source=module.SOURCE_NAME,
                data_status="review",
                source_ref=(module.SOURCE_NAME, paper_path),
            )
            if fields.authors:
                paper.authors_json = json.dumps(fields.authors, ensure_ascii=False)
                session.add(paper)
            paper_id = paper.id
            paper_code = paper.code
        message = f"导入成功，编号 {paper_code}" if created else (
            f"已存在于论文库（{paper_code}），本次补齐了来源信息"
        )
        if created and fields.abstract is None:
            message += "；来源没有提供摘要，关键词仅基于标题"
        return _finish_item(
            item_id, status="success", message=message, paper_id=paper_id
        )
    except ApiError as error:
        return _finish_item(item_id, status="failed", message=error.message)
    except Exception as error:  # noqa: BLE001 - 单条失败不中断整批
        logger.exception("保存失败：item=%s", item_id)
        return _finish_item(
            item_id, status="failed", message=f"保存失败：{type(error).__name__}"
        )


# ------------------------------------------------------------------ 后台执行


class TaskRunner:
    """进程内单线程任务执行器：同一时刻只处理一个任务，逐条提交。"""

    def __init__(self, cache: IndexCache | None = None) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        # 只记住显式传入的缓存；未传时在每次执行时读取模块级 shared_cache，
        # 这样替换 shared_cache（例如测试或热更新）能立即生效，
        # 不会因为构造时绑定而在后台线程里继续用旧对象。
        self._explicit_cache = cache

    def _resolve_cache(self) -> IndexCache:
        return self._explicit_cache or shared_cache

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, task_id: int) -> bool:
        """异步启动任务；已有任务在跑时返回 False（保持低并发）。"""
        with self._lock:
            if self.busy:
                return False
            self._stopping.clear()
            self._thread = threading.Thread(
                target=self._run,
                args=(task_id,),
                name=f"cvplatform-task-{task_id}",
                daemon=True,
            )
            self._thread.start()
            return True

    def stop(self) -> None:
        """请求停止（用于测试与停机）。"""
        self._stopping.set()

    def run_sync(self, task_id: int) -> None:
        """在前台同步处理一个任务。

        命令行采集用它逐任务推进并即时打印结果；接口层仍走后台线程，
        避免请求被长时间占用。
        """
        self._execute(task_id)

    def _run(self, task_id: int) -> None:
        from ..db.engine import session_scope

        # 依次处理排队中的任务：一次采集往往创建多个任务（每个会议年份一个），
        # 逐个跑完能让批量采集无人值守地推进，同时保持单实例低并发。
        current: int | None = task_id
        while current is not None and not self._stopping.is_set():
            try:
                self._execute(current)
            except Exception:  # noqa: BLE001 - 线程内异常只记录，不向上抛
                logger.exception("任务执行异常：task_id=%s", current)
                try:
                    with session_scope() as session:
                        task = session.get(CollectionTask, current)
                        if task is not None:
                            task.status = "interrupted"
                            task.message = "任务执行过程中出现异常，可继续处理。"
                            session.add(task)
                except Exception:  # noqa: BLE001
                    logger.exception("更新任务状态失败：task_id=%s", current)
            current = self._next_pending_task()

    def _next_pending_task(self) -> int | None:
        """取下一个待处理任务，没有则返回 None。"""
        from ..db.engine import session_scope

        with session_scope() as session:
            task = session.exec(
                select(CollectionTask)
                .where(CollectionTask.status == "pending")
                .order_by(CollectionTask.id)
                .limit(1)
            ).first()
            return task.id if task is not None else None

    def _execute(self, task_id: int) -> None:
        from ..db.engine import session_scope

        cache = self._resolve_cache()

        with session_scope() as session:
            task = session.get(CollectionTask, task_id)
            if task is None:
                return
            task.status = "running"
            task.started_at = task.started_at or _now()
            task.message = "正在处理…"
            session.add(task)

        processed = 0
        while not self._stopping.is_set():
            # 每轮开一个新会话处理一条：网络请求期间不持有写事务
            with session_scope() as session:
                item = session.exec(
                    select(CollectionTaskItem)
                    .where(
                        CollectionTaskItem.task_id == task_id,
                        CollectionTaskItem.status == "pending",
                    )
                    .order_by(CollectionTaskItem.line_no)
                    .limit(1)
                ).first()
                if item is None:
                    break
                item_id = item.id or 0
                line_no = item.line_no

            # 明细处理自带短事务，网络请求期间不持有写事务
            status = process_item(item_id, cache=cache)
            with session_scope() as session:
                task = session.get(CollectionTask, task_id)
                if task is not None:
                    refresh_counts(session, task)
                    _progress(
                        f"task {task_id}: 第 {line_no} 行 → {status}，"
                        f"成功 {task.success_count} 重复 {task.duplicate_count} "
                        f"失败 {task.failed_count}"
                    )
            processed += 1

        with session_scope() as session:
            task = session.get(CollectionTask, task_id)
            if task is None:
                return
            refresh_counts(session, task)
            # 处理过程中产生的关键词任务在批次结束后统一结算
            summary = process_pending(session)
            task.status = _settle_status(task)
            task.finished_at = _now()
            task.message = (
                f"处理完成：成功 {task.success_count}、重复 {task.duplicate_count}、"
                f"失败 {task.failed_count}；关键词处理 {summary.processed} 篇"
                f"（其中成功为空 {summary.empty} 篇）"
            )
            session.add(task)
            _progress(f"task {task_id} 结束：{task.status}")


runner = TaskRunner()


# ------------------------------------------------------------------ 恢复与重试


def recover_interrupted(session: Session, *, auto_resume: bool = False) -> list[int]:
    """启动时收敛被中断的任务：运行中 → interrupted，运行中明细退回待处理。

    auto_resume 为真时，有未完成明细的任务直接回到 pending，交给执行器依次处理；
    为假时保持 interrupted，等待使用者从界面继续。
    """
    tasks = session.exec(
        select(CollectionTask).where(
            col(CollectionTask.status).in_(("running", "pending"))
        )
    ).all()
    recovered: list[int] = []
    for task in tasks:
        for item in session.exec(
            select(CollectionTaskItem).where(
                CollectionTaskItem.task_id == task.id,
                CollectionTaskItem.status == "running",
            )
        ).all():
            item.status = "pending"
            item.message = "服务重启，任务已中断，可继续处理"
            item.updated_at = _now()
            session.add(item)
        refresh_counts(session, task)
        if auto_resume and (task.pending_count or task.running_count):
            task.status = "pending"
            task.message = "服务重启，任务已重新入队，等待处理"
        else:
            task.status = "interrupted"
            task.message = "服务重启，任务已中断，可继续处理"
        session.add(task)
        recovered.append(task.id or 0)
    return recovered


def resume_task(session: Session, task_id: int) -> CollectionTask:
    """继续处理把未完成明细重新入队的任务。"""
    task = session.get(CollectionTask, task_id)
    if task is None:
        raise ApiError(404, "task_not_found", "任务不存在。")
    if task.status == "running":
        raise ApiError(409, "task_already_running", "任务正在处理中，无需重复启动。")

    resumable = session.exec(
        select(CollectionTaskItem).where(
            CollectionTaskItem.task_id == task_id,
            col(CollectionTaskItem.status).in_(("pending", "running")),
        )
    ).all()
    if not resumable:
        if task.status == "success":
            raise ApiError(
                409, "task_not_resumable", "该任务已全部成功，无需继续处理。"
            )
        raise ApiError(409, "task_not_resumable", "该任务没有可继续处理的条目，可改用重试失败条目。")

    for item in resumable:
        if item.status == "running":
            item.status = "pending"
            item.updated_at = _now()
            session.add(item)
    task.status = "pending"
    task.message = "已重新入队，等待处理。"
    session.add(task)
    refresh_counts(session, task)
    return task


def retry_failed(session: Session, task_id: int) -> CollectionTask:
    """把失败明细退回待处理并重新入队；成功与重复条目不动。"""
    task = session.get(CollectionTask, task_id)
    if task is None:
        raise ApiError(404, "task_not_found", "任务不存在。")
    if task.status == "running":
        raise ApiError(409, "task_already_running", "任务正在处理中，请稍后再重试。")

    failed = session.exec(
        select(CollectionTaskItem).where(
            CollectionTaskItem.task_id == task_id,
            CollectionTaskItem.status == "failed",
        )
    ).all()
    if not failed:
        raise ApiError(
            409, "task_not_resumable", "该任务没有失败条目，无需重试。"
        )

    for item in failed:
        item.status = "pending"
        item.attempts += 0  # 次数在真正处理时累加
        item.message = None
        item.updated_at = _now()
        session.add(item)
    task.status = "pending"
    task.message = f"已把 {len(failed)} 条失败明细重新入队。"
    session.add(task)
    refresh_counts(session, task)
    return task


def paper_count(session: Session) -> int:
    return int(session.exec(select(func.count()).select_from(Paper)).one())
