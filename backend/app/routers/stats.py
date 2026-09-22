"""统计接口：概览、热点 Top、共现图谱与热度趋势。

契约见 开发设计与验收.md 第 7.5 节；错误统一为 {"detail": {"code", "message"}}。
本模块只负责参数解析与 HTTP 响应，聚合逻辑在 services/stats.py，
两者共用同一套分析集合与有效性规则（视图 v_analysis_paper / v_analysis_keyword）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..config import (
    STATS_GRAPH_LIMIT,
    STATS_GRAPH_MIN_EDGE,
    STATS_TOP_LIMIT,
)
from ..db.engine import session_scope
from ..services import stats

router = APIRouter(prefix="/api/stats", tags=["stats"])


def scope_params(
    conference: list[str] | None = Query(
        None,
        description="会议筛选，可重复或用逗号分隔（CVPR/ICCV/ECCV），留空表示全部",
    ),
    year: int | None = Query(None, description="单年简写，等价于 year_from=year_to"),
    year_from: int | None = Query(None, description="起始年份（含）"),
    year_to: int | None = Query(None, description="结束年份（含）"),
) -> stats.Scope:
    """四个统计接口共用的范围参数，解析与校验集中在一处。"""
    return stats.parse_scope(
        conference=conference, year=year, year_from=year_from, year_to=year_to
    )


def group_by_param(
    group_by: str | None = Query(
        None,
        description="分组方式：topic（默认，按主题归并）/ keyword（直接按关键词）",
    ),
) -> str:
    return stats.parse_group_by(group_by)


@router.get("/coverage", tags=["meta"])
def get_coverage() -> dict[str, object]:
    """数据覆盖明细：各会议年份的记录数与分析分母、来源分布、抽样性质。

    关于页与首页的范围说明都用它，避免两处各写一套覆盖口径。
    """
    with session_scope() as session:
        return stats.coverage_detail(session)


@router.get("/summary")
def get_summary(
    scope: stats.Scope = Depends(scope_params),
    group_by: str = Depends(group_by_param),
) -> dict[str, object]:
    """首页概览：分母、最热主题、未归类数量、排除量与覆盖情况。"""
    with session_scope() as session:
        return stats.summary(session, scope, group_by=group_by)


@router.get("/top")
def get_top(
    scope: stats.Scope = Depends(scope_params),
    group_by: str = Depends(group_by_param),
    limit: int = Query(STATS_TOP_LIMIT, ge=1, le=200, description="榜单条数"),
    exclude_unmapped: bool = Query(
        True,
        description="不把「未归类」当作分组参与排序（默认）；传 false 可让它参与，"
        "用于查看还有多少关键词没有归到主题",
    ),
) -> dict[str, object]:
    """热点榜单：按关联论文数排序，并列时按分组键升序保证顺序稳定。"""
    with session_scope() as session:
        return stats.top(
            session,
            scope,
            limit=limit,
            group_by=group_by,
            exclude_unmapped=exclude_unmapped,
        )


@router.get("/graph")
def get_graph(
    scope: stats.Scope = Depends(scope_params),
    group_by: str = Depends(group_by_param),
    limit: int = Query(STATS_GRAPH_LIMIT, ge=1, le=200, description="节点上限"),
    min_edge: int = Query(STATS_GRAPH_MIN_EDGE, ge=1, description="最小共现论文数"),
) -> dict[str, object]:
    """关键词图谱：节点大小表示关联论文数，边权表示同篇共现的去重论文数。"""
    with session_scope() as session:
        return stats.graph(
            session, scope, limit=limit, min_edge=min_edge, group_by=group_by
        )


@router.get("/trend")
def get_trend(
    scope: stats.Scope = Depends(scope_params),
    group_by: str = Depends(group_by_param),
    keys: str | None = Query(
        None, description="分组键，逗号分隔；留空取占比最高的若干个"
    ),
) -> dict[str, object]:
    """热度趋势：按会议与年份返回主题数量、分母、占比、总样本与排除数量。"""
    wanted = [item.strip() for item in (keys or "").split(",") if item.strip()]
    with session_scope() as session:
        return stats.trend(session, scope, keys=wanted or None, group_by=group_by)
