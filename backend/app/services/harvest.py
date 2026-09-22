"""真实数据采集（抽样）：把会议年份索引按固定规则抽样并落库。

设计依据：开发设计与验收.md 第 2.5、5 章与阶段 6 任务第 7 条。

抽样规则（确定性、可复现）：
    stride = max(1, floor(N / limit))
    取 L[0], L[stride], L[2*stride], ... 直到取满 limit 条
采用等距抽样而不是「取前 limit 条」，是为了避免来源页面按 session 分组的排序
把样本集中在单一主题簇；同时记录 N、stride 与实际条数，保证可复现。

采集本身做成任务（kind=harvest），逐条落库、可中断续跑；
已入库的条目标记为重复，因此重复运行不会产生重复记录。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlmodel import Session

from ..config import HARVEST_SAMPLE_LIMIT, TARGET_CONFERENCE_YEARS
from .index_cache import IndexedPaper, shared_cache
from .tasks import create_harvest_task, refresh_counts

logger = logging.getLogger("cvplatform.harvest")


@dataclass
class SamplingPlan:
    """一个会议年份的抽样计划，记录步长与实际条数便于复现。"""

    conference: str
    year: int
    total_available: int
    stride: int
    limit: int
    selected: list[IndexedPaper]


def plan_sampling(
    entries: list[IndexedPaper], *, conference: str, year: int, limit: int
) -> SamplingPlan:
    """按等距抽样规则从索引条目中选取样本。"""
    total = len(entries)
    if total == 0:
        return SamplingPlan(conference, year, 0, 1, limit, [])
    stride = max(1, total // limit)
    selected = [entries[index] for index in range(0, total, stride)][:limit]
    return SamplingPlan(conference, year, total, stride, limit, selected)


def build_plans(
    *,
    limit: int = HARVEST_SAMPLE_LIMIT,
    pairs: tuple[tuple[str, int], ...] = TARGET_CONFERENCE_YEARS,
    on_error=None,
) -> list[SamplingPlan]:
    """为每个目标组合载入索引并生成抽样计划。

    逐个组合处理：某个组合的索引取不到时跳过并记录，不影响其余组合。
    """
    plans: list[SamplingPlan] = []
    for conference, year in pairs:
        try:
            entries = shared_cache.load(conference, year, timeout=60.0)
        except Exception as error:  # noqa: BLE001 - 记录后继续
            if on_error is not None:
                on_error(conference, year, error)
            logger.warning("索引载入失败：%s %s → %s", conference, year, error)
            continue
        plans.append(
            plan_sampling(entries, conference=conference, year=year, limit=limit)
        )
    return plans


def create_harvest_tasks(session: Session, plans: list[SamplingPlan]) -> list[int]:
    """为每个抽样计划创建采集任务，返回任务 id 列表。"""
    task_ids: list[int] = []
    for plan in plans:
        titles = [(index, entry.title) for index, entry in enumerate(plan.selected)]
        if not titles:
            continue
        task = create_harvest_task(
            session,
            conference=plan.conference,
            year=plan.year,
            stride=plan.stride,
            limit=plan.limit,
            titles=titles,
        )
        refresh_counts(session, task)
        task_ids.append(task.id or 0)
        logger.info(
            "已创建采集任务：%s %s 可用 %s 条，步长 %s，抽样 %s 条",
            plan.conference,
            plan.year,
            plan.total_available,
            plan.stride,
            len(titles),
        )
    return task_ids


def describe_plan(plan: SamplingPlan) -> str:
    """给出可粘贴到文档里的抽样说明。"""
    return (
        f"{plan.conference} {plan.year}：来源索引共 {plan.total_available} 条，"
        f"步长 stride = max(1, {plan.total_available} // {plan.limit}) = {plan.stride}，"
        f"实际抽取 {len(plan.selected)} 条"
    )
