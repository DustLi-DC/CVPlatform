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

from ..config import KEYWORD_RULESET_VERSION
from ..models.entities import AppMeta, Paper
from .keyword_rules import KeywordExtractor, ExtractionResult
from .keywords import clear_system_keywords, sync_paper_keywords

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


def process_paper(session: Session, paper: Paper) -> ExtractionResult:
    """处理单篇论文（阶段 5 采集保存后立即调用）。"""
    extractor, _corpus = build_extractor(session)
    result = extractor.extract(paper.title, paper.abstract)
    apply_result(session, paper, result)
    return result


def pending_papers(session: Session, *, limit: int | None = None) -> list[Paper]:
    """取出需要处理的论文：未处理、处理失败，或规则版本已过期。"""
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


def process_pending(session: Session, *, limit: int | None = None) -> ProcessingSummary:
    """批量处理待处理论文；语料只拟合一次，逐篇抽取。

    供阶段 5 的单篇保存后调用，也供阶段 6、7 的批量任务复用。
    """
    batch = pending_papers(session, limit=limit)
    summary = ProcessingSummary()

    extractor, corpus = build_extractor(session)
    summary.corpus_size = extractor.corpus_size
    summary.effective_min_df = extractor.tier.effective_min_df
    summary.phrases_enabled = extractor.tier.phrases_enabled
    summary.config_signature = extractor.config_signature()

    for paper in batch:
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

    summary.remaining = len(pending_papers(session))
    _set_meta(session, "data_updated_at", _now())
    return summary
