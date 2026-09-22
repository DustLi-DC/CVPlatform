"""单篇采集编排：本地优先，未命中再检索公开来源。

设计依据：开发设计与验收.md 第 7.3 节，以及阶段 5 任务第 3、4 条。

流程：
1. 先在本地论文库检索（题目精确/关键词模糊），命中即直接返回，不发起外部请求；
2. 未命中时按情况选择在线来源：
   - 已知会议与年份 → 查该会议年份的索引页做**权威匹配**（能确定会议归属，
     且详情页提供摘要与原文链接）；
   - 会议或年份未知 → 用 OpenAlex 按题目检索，返回候选**交给使用者确认**；
3. 候选一律带相似度分数与「是否已在库中」标记，绝不自动选定。

OpenAlex 的候选经常无法归属到三大会议（ECCV 的 DOI 指向 Springer），
这种情况下如实标记 `conference=None`，由使用者补充，而不是猜一个会议。
"""

from __future__ import annotations

import os

from dataclasses import dataclass, field

from ..config import CONFERENCES
from ..models.entities import Paper
from .sources import cvf, ecva
from .sources.http import SourceError, SourceTimeout, SourceUnavailable

# 交互式单篇采集的总预算约 15 秒（见 开发设计与验收.md 第 8.2 节）。
# 收紧为「最多两次尝试 × 每次 6 秒」并配合 1 秒退避，最坏约 13 秒；
# 批量采集走来源模块的默认参数（10 秒 / 2 次重试），因为它是后台任务，可以慢。
# 两者都可用环境变量调整，便于按线上实际网络状况收紧或放宽。
def _env_float(name: str, default: float) -> float:
    try:
        return max(0.001, float(os.environ.get(name, "").strip() or default))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, "").strip() or default))
    except ValueError:
        return default


INTERACTIVE_TIMEOUT = _env_float("HTTP_INTERACTIVE_TIMEOUT_SECONDS", 6.0)
INTERACTIVE_RETRIES = _env_int("HTTP_INTERACTIVE_RETRIES", 1)
from .sources.openalex import RemoteCandidate, search_by_title, token_set_similarity
from .papers import find_by_dedup_key, build_dedup_key, normalize_title


@dataclass
class LookupOutcome:
    """一次查询的结果。`outcome` 明确区分四种情况，便于接口与前端分别呈现。"""

    outcome: str
    query: str
    # outcome='local_hit'
    papers: list[Paper] = field(default_factory=list)
    # outcome='remote_candidates'
    candidates: list[RemoteCandidate] = field(default_factory=list)
    # 诊断信息（来源、耗时、重试等），用于向使用者解释过程
    source: str | None = None
    message: str | None = None


# ---------------------------------------------------------------- 本地检索


def search_local(session, title: str, *, limit: int = 5) -> list[Paper]:
    """本地检索：先按归一化标题全等，再按关键词模糊。"""
    from sqlmodel import col, select

    normalized = normalize_title(title)
    exact = session.exec(
        select(Paper).where(Paper.title_normalized == normalized)
    ).first()
    if exact is not None:
        return [exact]

    pattern = f"%{title.strip().lower()}%"
    from sqlalchemy import func, or_

    rows = session.exec(
        select(Paper)
        .where(
            or_(
                func.lower(Paper.title).like(pattern),
                func.lower(Paper.code).like(pattern),
            )
        )
        .order_by(Paper.code)
        .limit(limit)
    ).all()
    return list(rows)


# ---------------------------------------------------------------- 在线检索


def _index_module(conference: str):
    """按会议选择索引来源：CVF 收录 CVPR/ICCV，ECCV 走 ECVA。"""
    if conference == "ECCV":
        return ecva
    return cvf


def lookup_index(
    conference: str, year: int, title: str, *, limit: int = 5
) -> list[RemoteCandidate]:
    """在指定会议年份的索引里按题目匹配，返回候选（按相似度降序）。"""
    module = _index_module(conference)
    if conference == "ECCV":
        entries = module.fetch_index(
            year, timeout=INTERACTIVE_TIMEOUT, retries=INTERACTIVE_RETRIES
        )
    else:
        entries = module.fetch_index(
            conference, year, timeout=INTERACTIVE_TIMEOUT, retries=INTERACTIVE_RETRIES
        )
    pairs = [(entry.title, entry.landing_url, entry.paper_path) for entry in entries]

    scored: list[RemoteCandidate] = []
    for entry_title, landing_url, paper_path in pairs:
        score = token_set_similarity(title, entry_title)
        if score < 0.5:
            continue
        scored.append(
            RemoteCandidate(
                source=module.SOURCE_NAME,
                source_id=paper_path,
                title=entry_title,
                year=year,
                conference=conference,
                landing_url=landing_url,
                match_score=score,
            )
        )
    scored.sort(key=lambda item: (-item.match_score, item.title))
    return scored[:limit]


def enrich_from_detail(candidate: RemoteCandidate) -> RemoteCandidate:
    """补取详情页，填充摘要、作者与原文链接（PDF）。

    会议年份已知时这是获取摘要的**唯一可靠途径**：OpenAlex 的会议版条目经常没有摘要。
    """
    module = _index_module(candidate.conference or "CVPR")
    fields = module.fetch_paper(
        candidate.source_id or "",
        timeout=INTERACTIVE_TIMEOUT,
        retries=INTERACTIVE_RETRIES,
    )
    candidate.abstract = fields.abstract or candidate.abstract
    candidate.pdf_url = fields.pdf_url
    candidate.landing_url = fields.landing_url or candidate.landing_url
    if fields.authors:
        candidate.authors = fields.authors
    if fields.title:
        candidate.title = fields.title
    if not candidate.abstract:
        candidate.notes.append("来源没有提供摘要，关键词将仅基于标题")
    if not candidate.pdf_url and not candidate.landing_url:
        candidate.notes.append("来源没有提供原文链接")
    return candidate


def lookup_remote(
    session,
    title: str,
    *,
    conference: str | None = None,
    year: int | None = None,
    limit: int = 5,
) -> LookupOutcome:
    """在线检索。会区分候选、无结果、超时与来源不可用四种情况。"""
    known_conference = conference if conference in CONFERENCES else None

    try:
        if known_conference and year:
            candidates = lookup_index(known_conference, year, title, limit=limit)
            source = _index_module(known_conference).SOURCE_NAME
            # 只对最相近的若干条补取详情页，控制外部请求次数
            for candidate in candidates[:2]:
                enrich_from_detail(candidate)
        else:
            candidates = search_by_title(
                title, timeout=INTERACTIVE_TIMEOUT, retries=INTERACTIVE_RETRIES
            )
            for candidate in candidates:
                candidate.match_score = token_set_similarity(title, candidate.title)
            candidates = [item for item in candidates if item.match_score >= 0.35]
            candidates.sort(key=lambda item: (-item.match_score, item.title))
            candidates = candidates[:limit]
            source = "openalex"
            for candidate in candidates:
                if candidate.conference is None:
                    candidate.notes.append(
                        "该来源无法确定会议归属（ECCV 的 DOI 指向出版社），请在表单中补充会议与年份"
                    )
    except SourceTimeout as error:
        return LookupOutcome(
            "remote_timeout", title, message=error.message, source=error.source
        )
    except SourceUnavailable as error:
        return LookupOutcome(
            "remote_unavailable", title, message=error.message, source=error.source
        )
    except SourceError as error:  # pragma: no cover - 兜底
        return LookupOutcome(
            "remote_unavailable", title, message=error.message, source=error.source
        )

    if not candidates:
        return LookupOutcome("remote_empty", title, source=source)

    for candidate in candidates:
        _mark_existing(session, candidate)

    return LookupOutcome(
        "remote_candidates", title, candidates=candidates, source=source
    )


def _mark_existing(session, candidate: RemoteCandidate) -> None:
    """标记候选是否已在库中，并给出已存在记录的编号。"""
    existing = None
    if candidate.conference and candidate.year:
        existing = find_by_dedup_key(
            session,
            build_dedup_key(candidate.conference, candidate.year, candidate.title),
        )
    if existing is None:
        # 会议未知时退化为按标题查找，避免把已在库的论文重复导入
        from sqlmodel import select

        existing = session.exec(
            select(Paper).where(
                Paper.title_normalized == normalize_title(candidate.title)
            )
        ).first()
    if existing is not None:
        candidate.already_exists = True
        candidate.existing_code = existing.code


def lookup(
    session,
    title: str,
    *,
    conference: str | None = None,
    year: int | None = None,
) -> LookupOutcome:
    """统一入口：先查本地，未命中再检索公开来源。"""
    clean_title = title.strip()
    if not clean_title:
        raise ValueError("查询语句不能为空")

    local_hits = search_local(session, clean_title)
    if local_hits:
        return LookupOutcome("local_hit", clean_title, papers=local_hits)

    return lookup_remote(session, clean_title, conference=conference, year=year)
