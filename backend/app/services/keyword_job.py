"""关键词处理任务：把抽取结果写入关键词关系与处理状态。

设计依据：开发设计与验收.md 第 4.1、5.2、5.5 节。

- 语料取自 v_corpus_paper（真实、会议年份有效、标题可用），**不要求已完成关键词处理**，
  因此首次导入时不存在循环依赖；
- 抽取成功后写 keyword_status='done' 并记录规则版本，论文进入分析集合；
- 「抽取成功但没有任何关键词」也是 done（只写状态、不写关系），仍计入分析分母；
- 抽取过程抛错才记为 'failed'，与「成功为空」区分开；
- 旧版本的系统关键词关系不删除，按版本保留；读取与统计只认当前版本。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import text
from sqlmodel import Session, select

from ..config import CONFERENCES, KEYWORD_RULESET_VERSION
from ..models.entities import AppMeta, Paper
from .keyword_rules import KeywordExtractor, ExtractionResult
from .keywords import (
    clear_system_keywords,
    current_ruleset_version,
    sync_paper_keywords,
)
from .maintenance import mark_analysis_changed

logger = logging.getLogger("cvplatform.keywords")


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _set_meta(session: Session, key: str, value: str) -> None:
    row = session.get(AppMeta, key)
    if row is None:
        session.add(AppMeta(key=key, value=value))
        return
    row.value = value
    session.add(row)


@dataclass
class ProcessingSummary:
    """一次处理的统计，便于接口与日志如实报告数量。"""

    corpus_size: int = 0
    processed: int = 0
    empty: int = 0
    failed: int = 0
    remaining: int = 0
    effective_min_df: int = 1
    phrases_enabled: bool = False
    config_signature: str = ""


def load_corpus_texts(session: Session) -> list[tuple[int, str]]:
    """取语料集合内每篇论文的可用文本（标题 + 摘要），返回 (id, text)。"""
    rows = session.execute(
        text("SELECT id, title, abstract FROM v_corpus_paper ORDER BY id")
    ).all()
    corpus: list[tuple[int, str]] = []
    for paper_id, title, abstract in rows:
        # 注意：局部变量不能叫 text，否则会遮蔽上面导入的 sqlalchemy.text
        document = f"{title} {abstract}" if abstract else str(title)
        corpus.append((int(paper_id), document))
    return corpus


def build_extractor(
    session: Session, *, ruleset_version: str = KEYWORD_RULESET_VERSION
):
    """在语料集合上拟合抽取器，并记录语料规模与拟合时间。"""
    corpus = load_corpus_texts(session)
    extractor = KeywordExtractor(ruleset_version=ruleset_version)
    extractor.fit([text for _, text in corpus])
    _set_meta(session, "idf_corpus_size", str(extractor.corpus_size))
    _set_meta(session, "idf_fit_at", _now())
    _set_meta(session, "keyword_config_signature", extractor.config_signature())
    return extractor, corpus


def apply_result(
    session: Session,
    paper: Paper,
    result: ExtractionResult,
) -> None:
    """把抽取结果写入关系与状态。成功为空与处理失败的写法在此区分。"""
    if paper.id is None:  # pragma: no cover - 调用方保证已持久化
        raise ValueError("paper 必须先持久化")

    names = [keyword.name for keyword in result.keywords]
    if names:
        sync_paper_keywords(
            session,
            paper,
            author_keywords=[],
            system_keywords=names,
            ruleset_version=result.ruleset_version,
        )
    else:
        # 成功但为空：清掉当前版本的系统关键词，状态仍记为 done
        clear_system_keywords(session, paper.id)

    paper.keyword_status = "done"
    paper.keyword_ruleset_version = result.ruleset_version
    paper.keyword_processed_at = _now()
    paper.updated_at = _now()
    session.add(paper)
    # 分析集合发生变化：让统计缓存整体失效
    mark_analysis_changed(session)


def status_counts(session: Session) -> dict[str, object]:
    """统计口径相关的数量汇总，供维护命令与 /api/keywords/status 复用。

    `pending_or_stale` 是「按需处理」要动的总量：未处理、处理失败，或规则版本过期。
    """
    current = current_ruleset_version(session)
    analysis_papers = session.execute(
        text("SELECT COUNT(*) FROM v_analysis_paper")
    ).scalar_one()
    corpus_papers = session.execute(
        text("SELECT COUNT(*) FROM v_corpus_paper")
    ).scalar_one()
    by_status = {
        str(status): int(count)
        for status, count in session.execute(
            text("SELECT keyword_status, COUNT(*) FROM paper GROUP BY keyword_status")
        ).all()
    }
    pending_or_stale = int(
        session.execute(
            text(
                "SELECT COUNT(*) FROM paper "
                "WHERE keyword_status IS NOT 'done' "
                "   OR keyword_ruleset_version IS NOT ("
                "        SELECT value FROM meta WHERE key = 'keyword_ruleset_version')"
            )
        ).scalar_one()
    )
    system_keywords = int(
        session.execute(
            text("SELECT COUNT(*) FROM keyword WHERE origin = 'system'")
        ).scalar_one()
    )
    mapped_keywords = int(
        session.execute(
            text(
                "SELECT COUNT(*) FROM keyword "
                "WHERE origin = 'system' AND topic_id IS NOT NULL"
            )
        ).scalar_one()
    )
    return {
        "analysis_papers": int(analysis_papers),
        "corpus_papers": int(corpus_papers),
        "by_status": by_status,
        "pending_or_stale": pending_or_stale,
        "ruleset_version": current,
        "system_keywords": system_keywords,
        "mapped_keywords": mapped_keywords,
    }


def process_paper(session: Session, paper: Paper) -> ExtractionResult:
    """处理单篇论文（阶段 5 采集保存后立即调用）。"""
    extractor, _corpus = build_extractor(session)
    result = extractor.extract(paper.title, paper.abstract)
    apply_result(session, paper, result)
    return result


def pending_papers(
    session: Session, *, limit: int | None = None, force: bool = False
) -> list[Paper]:
    """取出需要处理的论文：未处理、处理失败，或规则版本已过期。

    force = True 时忽略状态与版本，对语料集合内的全部论文重算。
    这条路径用于**规则或词表调整后的一致重算**：版本号已提升但库里还留着
    同版本号的旧结果时（校准过程中会出现），只有强制重算才能让口径与代码一致。
    """
    if force:
        statement = (
            select(Paper)
            .where(
                Paper.conference.in_(CONFERENCES),
                Paper.year > 0,
            )
            .order_by(Paper.id)
        )
    else:
        statement = (
            select(Paper)
            .where(
                (Paper.keyword_status != "done")
                | (Paper.keyword_ruleset_version != KEYWORD_RULESET_VERSION)
            )
            .order_by(Paper.id)
        )
    if limit is not None:
        statement = statement.limit(limit)
    return list(session.exec(statement).all())


# 每处理多少篇提交一次：语料扩大到数万篇后，整批一个事务会让 WAL 涨到几十 MB、
# 中断后进度全部丢失、也看不到任何进度。设计文档 5.6 明确要求「按 200 篇一批提交」。
KEYWORD_COMMIT_BATCH = 200


def process_pending(
    session: Session,
    *,
    limit: int | None = None,
    force: bool = False,
    on_progress=None,
) -> ProcessingSummary:
    """批量处理待处理论文；语料只拟合一次，逐篇抽取，按批提交。

    供阶段 5 的单篇保存后调用，也供阶段 6、7 的批量任务复用。
    `on_progress(已处理, 总数)` 用于命令行显示进度（不传则不回调）。
    """
    batch = pending_papers(session, limit=limit, force=force)
    total = len(batch)
    summary = ProcessingSummary()

    extractor, corpus = build_extractor(session)
    summary.corpus_size = extractor.corpus_size
    summary.effective_min_df = extractor.tier.effective_min_df
    summary.phrases_enabled = extractor.tier.phrases_enabled
    summary.config_signature = extractor.config_signature()

    for index, paper in enumerate(batch, start=1):
        try:
            result = extractor.extract(paper.title, paper.abstract)
            apply_result(session, paper, result)
            summary.processed += 1
            if result.is_empty:
                summary.empty += 1
        except Exception:  # noqa: BLE001 - 单篇失败不能中断整批
            logger.exception("关键词处理失败：paper_id=%s", paper.id)
            paper.keyword_status = "failed"
            paper.updated_at = _now()
            session.add(paper)
            summary.failed += 1

        # 按批提交：中断时已处理的批次保留，重跑只处理剩余部分
        if index % KEYWORD_COMMIT_BATCH == 0:
            _set_meta(session, "data_updated_at", _now())
            session.commit()
            if on_progress is not None:
                on_progress(index, total)

    summary.remaining = len(pending_papers(session))
    _set_meta(session, "data_updated_at", _now())
    return summary
