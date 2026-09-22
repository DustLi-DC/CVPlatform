"""论文管理接口。

契约见 开发设计与验收.md 第 7.2 节；错误统一为 {"detail": {"code", "message"}}。
本模块只负责参数解析与 HTTP 响应，业务逻辑在 services/papers.py。
"""

from __future__ import annotations

from fastapi import APIRouter, Query, status
from sqlmodel import Session

from ..config import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from ..db.engine import session_scope
from ..models.entities import Paper
from ..schemas.paper import (
    PaperCreateIn,
    PaperDetailOut,
    PaperListItem,
    PaperPageOut,
    PaperUpdateIn,
    QueryScope,
    RelatedPapersOut,
)
from ..services import papers as paper_service
from ..services.keywords import parse_keywords_json

router = APIRouter(prefix="/api/papers", tags=["papers"])


def _to_list_item(
    paper: Paper, keywords: list[dict[str, object]]
) -> PaperListItem:
    return PaperListItem(
        id=paper.id or 0,
        code=paper.code,
        code_scope_mismatch=paper_service.code_scope_mismatch(paper),
        code_note=paper_service.code_note(paper),
        title=paper.title,
        conference=paper.conference,  # type: ignore[arg-type]
        year=paper.year,
        display_status=paper_service.derive_display_status(paper),
        abstract_status=paper.abstract_status,  # type: ignore[arg-type]
        keyword_status=paper.keyword_status,  # type: ignore[arg-type]
        keywords=keywords,  # type: ignore[arg-type]
        landing_url=paper.landing_url,
        pdf_url=paper.pdf_url,
    )


def _to_detail(
    paper: Paper,
    keywords: list[dict[str, object]],
    sources: list[dict[str, object]],
) -> PaperDetailOut:
    base = _to_list_item(paper, keywords)
    return PaperDetailOut(
        **base.model_dump(),
        abstract=paper.abstract,
        authors=paper_service.serialize_authors(paper.authors_json),
        source_keywords=parse_keywords_json(paper.keywords_source_json),
        system_keywords=[
            str(item["name"]) for item in keywords if item.get("origin") == "system"
        ],
        sources=sources,  # type: ignore[arg-type]
        retrieved_at=paper.retrieved_at,
        updated_at=paper.updated_at,
    )


def _split_multi(values: list[str] | None) -> list[str]:
    """同时支持 ?conference=CVPR&conference=ICCV 与 ?conference=CVPR,ICCV 两种写法。"""
    if not values:
        return []
    result: list[str] = []
    for value in values:
        for part in value.split(","):
            cleaned = part.strip()
            if cleaned and cleaned not in result:
                result.append(cleaned)
    return result


@router.get("", response_model=PaperPageOut, summary="检索论文列表")
def list_papers(
    q: str = Query("", description="查询语句：题目、编号或关键词"),
    match: str = Query("fuzzy", description="fuzzy 模糊匹配 / exact 精确匹配"),
    conference: list[str] | None = Query(
        None, description="会议筛选，可重复传参或用逗号分隔"
    ),
    year: int | None = Query(None, description="单年简写，等价于 year_from=year_to"),
    year_from: int | None = Query(None, description="起始年份（含）"),
    year_to: int | None = Query(None, description="结束年份（含）"),
    keyword: str | None = Query(None, description="按关键词精确筛选"),
    topic: str | None = Query(None, description="按主题筛选"),
    data_status: str | None = Query(None),
    keyword_status: str | None = Query(None),
    sort: str = Query(
        "code", description="code / title / year / conference / created_at"
    ),
    order: str = Query("asc", description="asc / desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
) -> PaperPageOut:
    conferences = _split_multi(conference)
    effective_from = year_from if year_from is not None else year
    effective_to = year_to if year_to is not None else year

    with session_scope() as session:
        result = paper_service.query_papers(
            session,
            q=q,
            match=match,
            conferences=conferences,
            year_from=effective_from,
            year_to=effective_to,
            keyword=keyword,
            topic=topic,
            data_status=data_status,
            keyword_status=keyword_status,
            sort=sort,
            order=order,
            page=page,
            page_size=page_size,
        )
        items: list[Paper] = result["items"]  # type: ignore[assignment]
        keyword_map = paper_service.load_paper_keywords(
            session, [item.id or 0 for item in items]
        )
        payload = [
            _to_list_item(paper, keyword_map.get(paper.id or 0, [])) for paper in items
        ]

    return PaperPageOut(
        items=payload,
        total=int(result["total"]),  # type: ignore[arg-type]
        page=int(result["page"]),  # type: ignore[arg-type]
        page_size=int(result["page_size"]),  # type: ignore[arg-type]
        pages=int(result["pages"]),  # type: ignore[arg-type]
        scope=QueryScope(
            conferences=conferences,
            year_from=effective_from,
            year_to=effective_to,
        ),
    )


def _get_paper_or_404(session: Session, paper_id: int) -> Paper:
    paper = session.get(Paper, paper_id)
    if paper is None:
        raise paper_service.ApiError(404, "paper_not_found", "论文不存在。")
    return paper


@router.get("/{paper_id}", response_model=PaperDetailOut, summary="论文详情")
def get_paper(paper_id: int) -> PaperDetailOut:
    with session_scope() as session:
        paper = _get_paper_or_404(session, paper_id)
        keyword_map = paper_service.load_paper_keywords(session, [paper_id])
        source_map = paper_service.load_paper_sources(session, [paper_id])
        return _to_detail(
            paper, keyword_map.get(paper_id, []), source_map.get(paper_id, [])
        )


@router.get("/{paper_id}/related", response_model=RelatedPapersOut, summary="同主题论文")
def get_related_papers(
    paper_id: int, limit: int = Query(3, ge=1, le=20)
) -> RelatedPapersOut:
    with session_scope() as session:
        paper = _get_paper_or_404(session, paper_id)
        related = paper_service.related_papers(session, paper, limit=limit)
        keyword_map = paper_service.load_paper_keywords(
            session, [item.id or 0 for item in related]
        )
        payload = [
            _to_list_item(item, keyword_map.get(item.id or 0, [])) for item in related
        ]
    return RelatedPapersOut(items=payload)


@router.post(
    "",
    response_model=PaperDetailOut,
    status_code=status.HTTP_201_CREATED,
    summary="新增论文",
)
def create_paper(payload: PaperCreateIn) -> PaperDetailOut:
    with session_scope() as session:
        paper, created = paper_service.save_paper(
            session,
            title=payload.title,
            conference=payload.conference,
            year=payload.year,
            abstract=payload.abstract,
            author_keywords=payload.source_keywords,
            landing_url=payload.landing_url,
            pdf_url=payload.pdf_url,
            primary_source="manual",
            data_status="review",
        )
        # 手工新增走严格模式：命中已有记录时返回冲突，不静默合并。
        # 采集与批量导入走同一 save_paper，但把命中视为 duplicate 记入任务明细。
        if not created:
            raise paper_service.DuplicatePaperError(paper)
        keyword_map = paper_service.load_paper_keywords(session, [paper.id or 0])
        source_map = paper_service.load_paper_sources(session, [paper.id or 0])
        return _to_detail(
            paper, keyword_map.get(paper.id or 0, []), source_map.get(paper.id or 0, [])
        )


@router.patch("/{paper_id}", response_model=PaperDetailOut, summary="编辑论文")
def update_paper(paper_id: int, payload: PaperUpdateIn) -> PaperDetailOut:
    with session_scope() as session:
        paper = _get_paper_or_404(session, paper_id)
        updated = paper_service.update_paper(
            session,
            paper,
            title=payload.title,
            conference=payload.conference,
            year=payload.year,
            abstract=payload.abstract,
            author_keywords=payload.source_keywords,
            landing_url=payload.landing_url,
            pdf_url=payload.pdf_url,
            data_status=payload.data_status,
        )
        keyword_map = paper_service.load_paper_keywords(session, [paper_id])
        source_map = paper_service.load_paper_sources(session, [paper_id])
        return _to_detail(
            updated, keyword_map.get(paper_id, []), source_map.get(paper_id, [])
        )


@router.delete(
    "/{paper_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除论文（级联清理关联）",
)
def delete_paper(paper_id: int) -> None:
    with session_scope() as session:
        paper = _get_paper_or_404(session, paper_id)
        paper_service.delete_paper(session, paper)
