"""论文相关的请求与响应模型（Pydantic）。

字段命名沿用 snake_case 数据契约；缺失值一律用 null，不把缺失写成 0。
契约见 开发设计与验收.md 第 7.2 节。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ConferenceName = Literal["CVPR", "ICCV", "ECCV"]
DisplayStatus = Literal["complete", "review", "abstract_missing", "failed"]
AbstractStatusName = Literal["present", "missing"]
KeywordStatusName = Literal["pending", "running", "done", "failed"]
KeywordOriginName = Literal["author", "system"]


class PaperKeywordOut(BaseModel):
    name: str
    origin: KeywordOriginName
    topic: str | None = Field(default=None, description="归并到的主題；未归类为 null")


class PaperSourceOut(BaseModel):
    source: str
    source_id: str
    url: str | None = None
    retrieved_at: str | None = None


class PaperListItem(BaseModel):
    id: int
    code: str
    code_scope_mismatch: bool = Field(
        description="编号分配时的会议年份与当前值不一致时为 true"
    )
    code_note: str | None = None
    title: str
    conference: ConferenceName
    year: int
    display_status: DisplayStatus
    abstract_status: AbstractStatusName
    keyword_status: KeywordStatusName
    keywords: list[PaperKeywordOut] = []
    landing_url: str | None = None
    pdf_url: str | None = None


class PaperDetailOut(PaperListItem):
    abstract: str | None = None
    authors: list[str] = []
    source_keywords: list[str] = []
    system_keywords: list[str] = []
    sources: list[PaperSourceOut] = []
    retrieved_at: str | None = None
    updated_at: str | None = None


class QueryScope(BaseModel):
    """回显本次请求实际生效的筛选范围，便于前端核对与展示已生效条件。"""

    conferences: list[str] = []
    year_from: int | None = None
    year_to: int | None = None


class StatsMode(BaseModel):
    """来自统计页时实际生效的口径约束，回显给界面显示「统计口径」条件。"""

    keyword_origin: str
    ruleset_version: str
    in_analysis_set: bool


class PaperPageOut(BaseModel):
    items: list[PaperListItem]
    total: int
    page: int
    page_size: int
    pages: int
    scope: QueryScope
    # 非统计口径跳转时为 null
    stats_mode: StatsMode | None = None


class PaperCreateIn(BaseModel):
    title: str = Field(min_length=1)
    conference: ConferenceName
    year: int
    abstract: str | None = None
    source_keywords: list[str] = []
    landing_url: str | None = None
    pdf_url: str | None = None


class PaperUpdateIn(BaseModel):
    """部分更新：未提供的字段保持不变。编号不可修改。"""

    title: str | None = None
    conference: ConferenceName | None = None
    year: int | None = None
    abstract: str | None = None
    source_keywords: list[str] | None = None
    landing_url: str | None = None
    pdf_url: str | None = None
    data_status: Literal["complete", "review", "failed"] | None = None


class RelatedPapersOut(BaseModel):
    items: list[PaperListItem]


class ErrorBody(BaseModel):
    code: str
    message: str
    existing: dict[str, object] | None = None


class ErrorResponse(BaseModel):
    detail: ErrorBody
