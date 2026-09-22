"""单篇采集接口：本地优先查询，未命中后在线检索，确认后入库。

契约见 开发设计与验收.md 第 7.3 节。四种在线结局分别用不同的 outcome 表达，
不使用「成功」掩盖缺失信息：
- local_hit            本地命中
- remote_candidates    联网找到候选（必须由使用者确认，不自动选定）
- remote_empty         联网没有找到
- remote_timeout       联网超时（504）
- remote_unavailable   来源不可用（502）
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..config import CONFERENCES
from ..db.engine import session_scope
from ..models.entities import Paper
from ..schemas.paper import PaperDetailOut
from ..services import papers as paper_service
from ..services.collector import lookup
from ..services.keyword_job import process_pending

router = APIRouter(prefix="/api/collect", tags=["collect"])


class LookupRequest(BaseModel):
    title: str = Field(min_length=1, description="论文完整题目或查询语句")
    conference: Literal["CVPR", "ICCV", "ECCV"] | None = None
    year: int | None = None


class LocalPaperRef(BaseModel):
    id: int
    code: str
    title: str
    conference: str
    year: int


class CandidateOut(BaseModel):
    source: str
    source_id: str
    title: str
    year: int | None = None
    conference: str | None = Field(
        default=None, description="无法确定会议归属时为 null，需使用者补充"
    )
    venue: str | None = None
    doi: str | None = None
    landing_url: str | None = None
    pdf_url: str | None = None
    abstract: str | None = None
    abstract_missing: bool = Field(description="来源是否没有提供摘要")
    authors: list[str] = []
    work_type: str | None = None
    match_score: float
    already_exists: bool = False
    existing_code: str | None = None
    notes: list[str] = []


class LookupResponse(BaseModel):
    outcome: Literal[
        "local_hit",
        "remote_candidates",
        "remote_empty",
        "remote_timeout",
        "remote_unavailable",
    ]
    query: str
    source: str | None = None
    message: str | None = None
    papers: list[LocalPaperRef] = []
    candidates: list[CandidateOut] = []


class ConfirmRequest(BaseModel):
    """确认导入某条候选。字段来自候选，会议与年份允许使用者补充后提交。"""

    title: str = Field(min_length=1)
    conference: Literal["CVPR", "ICCV", "ECCV"]
    year: int
    source: str
    source_id: str
    abstract: str | None = None
    authors: list[str] = []
    landing_url: str | None = None
    pdf_url: str | None = None


@router.post("/lookup", response_model=LookupResponse, summary="本地优先查询，未命中再联网")
def collect_lookup(payload: LookupRequest) -> LookupResponse:
    if payload.year is not None and payload.year <= 0:
        raise paper_service.ApiError(400, "invalid_parameter", "年份必须是正整数。")
    if payload.conference is not None and payload.conference not in CONFERENCES:
        raise paper_service.ApiError(
            400, "invalid_parameter", "会议必须是 CVPR、ICCV、ECCV 之一。"
        )

    with session_scope() as session:
        result = lookup(
            session,
            payload.title,
            conference=payload.conference,
            year=payload.year,
        )

        if result.outcome == "local_hit":
            return LookupResponse(
                outcome="local_hit",
                query=result.query,
                papers=[
                    LocalPaperRef(
                        id=paper.id or 0,
                        code=paper.code,
                        title=paper.title,
                        conference=paper.conference,
                        year=paper.year,
                    )
                    for paper in result.papers
                ],
            )

        if result.outcome == "remote_candidates":
            return LookupResponse(
                outcome="remote_candidates",
                query=result.query,
                source=result.source,
                candidates=[
                    CandidateOut(
                        source=item.source,
                        source_id=item.source_id,
                        title=item.title,
                        year=item.year,
                        conference=item.conference,
                        venue=item.venue,
                        doi=item.doi,
                        landing_url=item.landing_url,
                        pdf_url=item.pdf_url,
                        abstract=item.abstract,
                        abstract_missing=item.abstract is None,
                        authors=item.authors,
                        work_type=item.work_type,
                        match_score=item.match_score,
                        already_exists=item.already_exists,
                        existing_code=item.existing_code,
                        notes=item.notes,
                    )
                    for item in result.candidates
                ],
            )

        body = LookupResponse(
            outcome=result.outcome,  # type: ignore[arg-type]
            query=result.query,
            source=result.source,
            message=result.message,
        )

    # 超时与来源不可用使用明确的 HTTP 状态，便于前端与调用方分别处理
    if body.outcome == "remote_timeout":
        raise paper_service.ApiError(504, "upstream_timeout", body.message or "在线检索超时。")
    if body.outcome == "remote_unavailable":
        raise paper_service.ApiError(
            502, "upstream_unavailable", body.message or "在线来源不可用。"
        )
    return body


@router.post(
    "/confirm",
    response_model=PaperDetailOut,
    summary="确认导入候选（复用统一校验与去重）",
)
def collect_confirm(payload: ConfirmRequest) -> PaperDetailOut:
    from ..routers.papers import _to_detail

    if payload.year <= 0:
        raise paper_service.ApiError(400, "invalid_parameter", "年份必须是正整数。")

    with session_scope() as session:
        paper, created = paper_service.save_paper(
            session,
            title=payload.title,
            conference=payload.conference,
            year=payload.year,
            abstract=payload.abstract,
            author_keywords=[],
            landing_url=payload.landing_url,
            pdf_url=payload.pdf_url,
            primary_source=payload.source,
            data_status="review",
            source_ref=(payload.source, payload.source_id),
        )
        if payload.authors:
            import json

            paper.authors_json = json.dumps(payload.authors, ensure_ascii=False)
            session.add(paper)
            session.flush()

        # 采集成功后立即处理关键词，使论文尽快进入分析集合
        process_pending(session, limit=20)

        # 重新读取：关键词状态与关系由处理任务更新
        session.refresh(paper)
        keyword_map = paper_service.load_paper_keywords(session, [paper.id or 0])
        source_map = paper_service.load_paper_sources(session, [paper.id or 0])
        detail = _to_detail(
            paper, keyword_map.get(paper.id or 0, []), source_map.get(paper.id or 0, [])
        )
        detail.code_note = (
            None if created else "该论文已在库中，本次确认补齐了来源与缺失字段"
        )
        return detail
