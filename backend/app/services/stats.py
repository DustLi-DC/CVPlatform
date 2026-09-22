"""统计服务：热点 Top、共现图谱与热度趋势。

设计依据：开发设计与验收.md 第 4 章（分析集合与统计口径）与第 7.5 节（接口契约）。

口径要点（全部实现集中在建议阅读顺序里的这几条）：

- **唯一入口**：所有统计只查 `v_analysis_paper` 与 `v_analysis_keyword` 两个视图，
  版本、来源（只算系统关键词）与分析集合三条件已固化在视图里，
  调用方不写、也不允许自己写这三条件，避免口径分散。
- **分母**：`denominator(scope) = |分析集合 ∩ scope|`。「关键词处理成功但结果为空」
  的论文仍计入分母，因此分母取自视图的论文计数，**不用关键词关联反推**。
- **去重**：同一篇论文对同一主题最多计一次（`COUNT(DISTINCT paper_id)`）；
  一篇论文可属于多个主题，各主题占比之和不必等于 100%。
- **跨组加权**：先合并计数与分母再相除，绝不平均各组的百分比。
- **缺失与零的区别**：分母为 0 时 `share = null`；有样本但主题不存在时 `count = 0`、
  `share = 0.0`。会议年份在库中没有任何记录时 `has_data = false`——**没有记录不等于该届没举办**，
  返回 null 而不画成 0，并同时给出 `missing_conference_years` 说明是样本未覆盖。
- **不在请求中抽词或拟合**：只做 SQL 聚合；图谱的边在 Python 里用计数器统计，
  不构造稠密矩阵，也不加载全量关键词文本。
"""

from __future__ import annotations

import functools
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass

from sqlalchemy import text
from sqlmodel import Session

from ..config import (
    CONFERENCES,
    HARVEST_SAMPLE_LIMIT,
    STATS_CACHE_MAX_ENTRIES,
    STATS_DEFAULT_GROUP_BY,
    STATS_GRAPH_LIMIT,
    STATS_GRAPH_MIN_EDGE,
    STATS_TOP_LIMIT,
    STATS_TOP_LIMIT_MAX,
    TARGET_CONFERENCE_YEARS,
)
from ..models.entities import AppMeta
from .maintenance import read_analysis_version
from .papers import ApiError

logger = logging.getLogger("cvplatform.stats")

GROUP_BY_TOPIC = "topic"
GROUP_BY_KEYWORD = "keyword"
GROUP_BY_CHOICES: tuple[str, ...] = (GROUP_BY_TOPIC, GROUP_BY_KEYWORD)

# 「未归类」分组：映射不到主题的关键词如实归入这里，不隐藏、不强行合并
UNMAPPED_KEY = "__unmapped__"
UNMAPPED_NAME = "未归类"

RULESET_KEY = "keyword_ruleset_version"


@dataclass(frozen=True)
class Scope:
    """统计范围：会议集合 × 年份区间。"""

    conferences: tuple[str, ...]
    year_from: int | None = None
    year_to: int | None = None

    def describe(self) -> dict[str, object]:
        return {
            "conferences": list(self.conferences),
            "year_from": self.year_from,
            "year_to": self.year_to,
        }


def parse_scope(
    *,
    conference: list[str] | None = None,
    year: int | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
) -> Scope:
    """解析并校验统计范围参数。

    `year` 是 `year_from = year_to = year` 的简写，与论文列表接口保持一致；
    同时给出 year 与 year_from/year_to 时以显式的区间为准并报错，避免歧义。
    """
    conferences: list[str] = []
    for item in conference or []:
        for part in str(item).split(","):
            name = part.strip().upper()
            if not name:
                continue
            if name not in CONFERENCES:
                raise ApiError(
                    400,
                    "invalid_parameter",
                    f"会议只能是 {'/'.join(CONFERENCES)} 之一，收到 {name}。",
                )
            if name not in conferences:
                conferences.append(name)
    scope_conferences = tuple(conferences) if conferences else CONFERENCES

    if year is not None and (year_from is not None or year_to is not None):
        raise ApiError(
            400,
            "invalid_parameter",
            "year 与 year_from/year_to 不能同时使用，请只保留一种写法。",
        )
    if year is not None:
        year_from = year_to = year

    for value, label in ((year_from, "year_from"), (year_to, "year_to")):
        if value is not None and value <= 0:
            raise ApiError(400, "invalid_parameter", f"{label} 必须是正整数。")
    if year_from is not None and year_to is not None and year_from > year_to:
        raise ApiError(400, "invalid_parameter", "year_from 不能大于 year_to。")

    return Scope(conferences=scope_conferences, year_from=year_from, year_to=year_to)


def parse_group_by(value: str | None) -> str:
    """校验分组方式；不传时用后端默认值 topic（前端阶段 8 之前不传该参数）。"""
    group_by = (value or STATS_DEFAULT_GROUP_BY).strip().lower()
    if group_by not in GROUP_BY_CHOICES:
        raise ApiError(
            400,
            "invalid_parameter",
            f"group_by 只能是 {'/'.join(GROUP_BY_CHOICES)} 之一。",
        )
    return group_by


def _scope_clause(scope: Scope, *, alias: str, params: dict[str, object]) -> str:
    """生成会议年份范围条件；参数一律走绑定变量。"""
    clauses: list[str] = []
    names = [f":conf_{index}" for index in range(len(scope.conferences))]
    for index, name in enumerate(scope.conferences):
        params[f"conf_{index}"] = name
    clauses.append(f"{alias}.conference IN ({', '.join(names)})")
    if scope.year_from is not None:
        clauses.append(f"{alias}.year >= :year_from")
        params["year_from"] = scope.year_from
    if scope.year_to is not None:
        clauses.append(f"{alias}.year <= :year_to")
        params["year_to"] = scope.year_to
    return " AND ".join(clauses)


def _current_ruleset(session: Session) -> str:
    row = session.get(AppMeta, RULESET_KEY)
    return row.value if row is not None and row.value else ""


def _now_updated_at(session: Session) -> str | None:
    row = session.get(AppMeta, "data_updated_at")
    return row.value if row is not None else None


# ------------------------------------------------------------------ 分母与排除量


def denominator(session: Session, scope: Scope) -> int:
    """范围内分析集合的论文数（分母的唯一来源）。"""
    params: dict[str, object] = {}
    clause = _scope_clause(scope, alias="ap", params=params)
    value = session.execute(
        text(f"SELECT COUNT(*) FROM v_analysis_paper ap WHERE {clause}"), params
    ).scalar_one()
    return int(value)


def total_sample(session: Session, scope: Scope) -> int:
    """范围内**全部**论文记录数（含待处理与失败），用于说明样本总量。"""
    params: dict[str, object] = {}
    clause = _scope_clause(scope, alias="p", params=params)
    value = session.execute(
        text(
            "SELECT COUNT(*) FROM paper p "
            "WHERE p.conference IN ('CVPR', 'ICCV', 'ECCV') AND p.year > 0 "
            f"AND {clause}"
        ),
        params,
    ).scalar_one()
    return int(value)


def excluded_counts(session: Session, scope: Scope) -> dict[str, int]:
    """范围内被排除在分母之外的论文数。

    四个桶**互斥**，按优先级判定，避免一次提示里把同一篇论文数两遍：
    标题不可用 > 待重算（版本过期）> 处理失败 > 待处理（含处理中）。
    """
    params: dict[str, object] = {}
    clause = _scope_clause(scope, alias="p", params=params)
    ruleset = _current_ruleset(session)
    params["ruleset"] = ruleset
    row = session.execute(
        text(
            f"""
            SELECT
              SUM(CASE WHEN length(p.title_normalized) < 4 THEN 1 ELSE 0 END)
                AS invalid_title,
              SUM(CASE WHEN length(p.title_normalized) >= 4
                        AND p.keyword_status = 'done'
                        AND p.keyword_ruleset_version IS NOT :ruleset
                       THEN 1 ELSE 0 END) AS stale,
              SUM(CASE WHEN length(p.title_normalized) >= 4
                        AND p.keyword_status = 'failed'
                       THEN 1 ELSE 0 END) AS failed,
              SUM(CASE WHEN length(p.title_normalized) >= 4
                        AND p.keyword_status IN ('pending', 'running')
                       THEN 1 ELSE 0 END) AS pending
            FROM paper p
            WHERE p.conference IN ('CVPR', 'ICCV', 'ECCV') AND p.year > 0
              AND {clause}
            """
        ),
        params,
    ).first()
    if row is None:  # pragma: no cover - 聚合查询必然返回一行
        return {"pending": 0, "failed": 0, "stale": 0, "invalid_title": 0}
    # 顺序必须与上面 SELECT 的列顺序一致：invalid_title、stale、failed、pending
    return {
        "invalid_title": int(row[0] or 0),
        "stale": int(row[1] or 0),
        "failed": int(row[2] or 0),
        "pending": int(row[3] or 0),
    }


def _group_projection(group_by: str) -> str:
    """分组键与展示名。topic 分组时未映射的关键词归入「未归类」。"""
    if group_by == GROUP_BY_KEYWORD:
        return (
            "k.name_normalized AS group_key, "
            "k.name AS group_label, "
            "0 AS is_unmapped"
        )
    return (
        f"COALESCE(t.slug, '{UNMAPPED_KEY}') AS group_key, "
        f"COALESCE(t.name, '{UNMAPPED_NAME}') AS group_label, "
        "CASE WHEN t.id IS NULL THEN 1 ELSE 0 END AS is_unmapped"
    )


def _analysis_keyword_from(group_by: str) -> str:
    """统计的 FROM 子句：分析集合 → 系统关键词 → 主题（按需）。"""
    join_topic = (
        "LEFT JOIN topic t ON t.id = k.topic_id AND t.is_active = 1"
        if group_by == GROUP_BY_TOPIC
        else ""
    )
    return (
        "FROM v_analysis_keyword ak "
        "JOIN v_analysis_paper ap ON ap.id = ak.paper_id "
        "JOIN keyword k ON k.id = ak.keyword_id "
        f"{join_topic}"
    )


def _unmapped_block(
    session: Session, scope: Scope, group_by: str
) -> dict[str, object]:
    """「未归类」的规模：不参与榜单排序，但**始终如实报告**数量与占比。

    默认不参与排序的理由来自实测：1200 篇样本中每一篇都至少有一个未归类关键词，
    未归类论文数恒等于分母（占比 100%），把它当成一个「主题」排在第一位毫无信息量。
    但它必须可见——否则等于把「有数千个关键词没有归到任何主题」这件事藏起来。
    """
    if group_by == GROUP_BY_KEYWORD:
        return {
            "applies": False,
            "keyword_total": 0,
            "paper_count": 0,
            "share": None,
        }
    params: dict[str, object] = {}
    clause = _scope_clause(scope, alias="ap", params=params)
    row = session.execute(
        text(
            "SELECT COUNT(DISTINCT ak.keyword_id), COUNT(DISTINCT ak.paper_id) "
            "FROM v_analysis_keyword ak "
            "JOIN v_analysis_paper ap ON ap.id = ak.paper_id "
            "JOIN keyword k ON k.id = ak.keyword_id "
            f"WHERE {clause} AND k.topic_id IS NULL"
        ),
        params,
    ).first()
    keyword_total, paper_count = (
        (int(row[0] or 0), int(row[1] or 0)) if row is not None else (0, 0)
    )
    return {
        "applies": True,
        "keyword_total": keyword_total,
        "paper_count": paper_count,
        "share": _share(paper_count, denominator(session, scope)),
    }


def _key_total(session: Session, scope: Scope, group_by: str) -> int:
    """范围内出现过的分组数量（主题数量；未归类不计入，见 _unmapped_block）。"""
    params: dict[str, object] = {}
    clause = _scope_clause(scope, alias="ap", params=params)
    filter_unmapped = " AND t.id IS NOT NULL" if group_by == GROUP_BY_TOPIC else ""
    value = session.execute(
        text(
            "SELECT COUNT(*) FROM ("
            f"  SELECT {_group_projection(group_by)} "
            f"  {_analysis_keyword_from(group_by)} "
            f"  WHERE {clause}{filter_unmapped} "
            "  GROUP BY group_key"
            ")"
        ),
        params,
    ).scalar_one()
    return int(value)


def _coverage(session: Session) -> dict[str, object]:
    """数据覆盖情况：如实说明样本性质与未覆盖的目标组合。"""
    rows = session.execute(
        text("SELECT conference, year, COUNT(*) FROM paper GROUP BY 1, 2")
    ).all()
    present = {(str(conference), int(year)): int(count) for conference, year, count in rows}
    targets = [(conference, year) for conference, year in TARGET_CONFERENCE_YEARS]
    missing = [
        {"conference": conference, "year": year}
        for conference, year in targets
        if present.get((conference, year), 0) == 0
    ]
    limit_row = session.get(AppMeta, "harvest_sample_limit")
    if limit_row is not None and limit_row.value.isdigit():
        sampled = True
        sample_limit: int | None = int(limit_row.value)
        basis = "meta"
    elif present and all(
        present.get(target, 0) == HARVEST_SAMPLE_LIMIT for target in targets
    ):
        # 每个目标组合都恰好等于抽样上限，说明是按抽样规则采集的样本
        sampled = True
        sample_limit = HARVEST_SAMPLE_LIMIT
        basis = "counts_match_limit"
    else:
        sampled = False
        sample_limit = None
        basis = "unknown"
    return {
        "conference_years": len(present),
        "sampled": sampled,
        "sample_limit_per_conference_year": sample_limit,
        "sample_basis": basis,
        "missing_conference_years": missing,
    }


# ------------------------------------------------------------------ 缓存


_CACHE: dict[str, tuple[int, dict[str, object]]] = {}


def _cache_get(key: str, version: int) -> dict[str, object] | None:
    hit = _CACHE.get(key)
    if hit is None or hit[0] != version:
        return None
    return hit[1]


def _cache_put(key: str, version: int, payload: dict[str, object]) -> None:
    if len(_CACHE) >= STATS_CACHE_MAX_ENTRIES:
        # 简单容量控制：超限时整体清空，避免为一个统计缓存维护额外的 LRU 状态
        _CACHE.clear()
    _CACHE[key] = (version, payload)


def clear_cache() -> None:
    """清空进程内统计缓存（测试与维护命令使用）。"""
    _CACHE.clear()


def _cached_response(func):
    """按「数据库 + 分析集合版本 + 规则版本 + 口径参数」缓存统计响应。

    同一进程内（后端为单 worker）重复请求同口径时直接复用上次聚合结果；
    任何论文增删改、关键词写入、主题映射变化、规则版本切换都会让 analysis_version 自增，
    从而整体失效。不做按时间过期的猜测式缓存——那会返回「看起来新、实际过期」的数字。

    键里带上数据库路径与规则版本：本进程可能先后指向不同数据库（测试与本地切换环境），
    只按 version 缓存会把上一个库的结果当成新库的结果返回。
    """
    from ..config import resolve_database_path

    @functools.wraps(func)
    def wrapper(session: Session, scope: Scope, **kwargs) -> dict[str, object]:
        key = "|".join(
            [
                str(resolve_database_path()),
                str(read_analysis_version(session)),
                _current_ruleset(session),
                func.__name__,
                str(scope.describe()),
                str(sorted(kwargs.items())),
            ]
        )
        hit = _cache_get(key, read_analysis_version(session))
        if hit is not None:
            return hit
        payload = func(session, scope, **kwargs)
        _cache_put(key, read_analysis_version(session), payload)
        return payload

    return wrapper


# ------------------------------------------------------------------ Top


def _top_rows(
    session: Session, scope: Scope, group_by: str, limit: int
) -> list[tuple[str, str, int, int]]:
    """按关联论文数分组聚合，返回 (group_key, group_label, is_unmapped, count)。

    与 top() 同口径：**未归类不参与排序**。概览的「最热主题」也走这里，
    否则概览会显示「未归类 1200 篇」当第一名，与榜单自相矛盾。
    """
    params: dict[str, object] = {"limit": limit}
    clause = _scope_clause(scope, alias="ap", params=params)
    filter_unmapped = " AND t.id IS NOT NULL" if group_by == GROUP_BY_TOPIC else ""
    rows = session.execute(
        text(
            f"SELECT {_group_projection(group_by)}, COUNT(DISTINCT ak.paper_id) AS paper_count "
            f"{_analysis_keyword_from(group_by)} "
            f"WHERE {clause}{filter_unmapped} "
            "GROUP BY group_key "
            # 并列名次按分组键升序，保证同一查询多次调用顺序稳定
            "ORDER BY paper_count DESC, group_key ASC "
            "LIMIT :limit"
        ),
        params,
    ).all()
    return [
        (str(key), str(label), int(unmapped), int(count))
        for key, label, unmapped, count in rows
    ]


def _share(count: int, base: int) -> float | None:
    """占比：分母为 0 时返回 null，不把缺失写成 0。"""
    if base <= 0:
        return None
    return round(count / base * 100, 4)


@_cached_response
def top(
    session: Session,
    scope: Scope,
    *,
    limit: int = STATS_TOP_LIMIT,
    group_by: str = GROUP_BY_TOPIC,
    exclude_unmapped: bool = True,
) -> dict[str, object]:
    """热点榜单。limit 超过上限时按上限截断并如实回报。

    exclude_unmapped 默认为 True：未归类不是主题，默认不占用榜单名额，
    但它的规模始终在 unmapped 字段里给出（见 _unmapped_block 的说明）。
    传 false 时未归类作为一个分组参与排序，用于排查「还有多少词没归到主题」。
    """
    if limit <= 0:
        raise ApiError(400, "invalid_parameter", "limit 必须是正整数。")
    effective_limit = min(limit, STATS_TOP_LIMIT_MAX)
    base = denominator(session, scope)
    group_names = _topic_group_names(session)

    # 未归类是否参与排序：默认排除，避免它恒等于分母而占住榜首
    filter_unmapped = (
        "AND t.id IS NOT NULL " if exclude_unmapped and group_by == GROUP_BY_TOPIC else ""
    )
    params: dict[str, object] = {"limit": effective_limit}
    clause = _scope_clause(scope, alias="ap", params=params)
    rows = session.execute(
        text(
            f"SELECT {_group_projection(group_by)}, COUNT(DISTINCT ak.paper_id) AS paper_count "
            f"{_analysis_keyword_from(group_by)} "
            f"WHERE {clause} {filter_unmapped}"
            "GROUP BY group_key "
            "ORDER BY paper_count DESC, group_key ASC "
            "LIMIT :limit"
        ),
        params,
    ).all()

    items = [
        {
            "rank": rank,
            "key": str(key),
            "name": str(label),
            "group": None if group_by == GROUP_BY_KEYWORD else group_names.get(str(key)),
            "is_unmapped": bool(unmapped),
            "count": int(count),
            "share": _share(int(count), base),
        }
        for rank, (key, label, unmapped, count) in enumerate(rows, start=1)
    ]
    return {
        "scope": scope.describe(),
        "denominator": base,
        "total_sample": total_sample(session, scope),
        "excluded": excluded_counts(session, scope),
        "items": items,
        "key_total": _key_total(session, scope, group_by),
        "unmapped": _unmapped_block(session, scope, group_by),
        "has_data": base > 0,
        "limit": effective_limit,
        "limit_truncated": limit > effective_limit,
        "group_by": group_by,
        "exclude_unmapped": exclude_unmapped,
    }


def _topic_group_names(session: Session) -> dict[str, str | None]:
    """一次取出所有主题的分组名，供本次请求内的多个分组使用。

    不放在模块级缓存里：主题表可以在服务运行期间被重载（reload-topics），
    缓存住分组名会让界面继续显示旧分组，属于「看起来新、实际过期」的结果。
    """
    rows = session.execute(text("SELECT slug, group_name FROM topic")).all()
    return {str(slug): (group or None) for slug, group in rows}


# ------------------------------------------------------------------ 图谱


@_cached_response
def graph(
    session: Session,
    scope: Scope,
    *,
    limit: int = STATS_GRAPH_LIMIT,
    min_edge: int = STATS_GRAPH_MIN_EDGE,
    group_by: str = GROUP_BY_TOPIC,
    exclude_unmapped: bool = True,
) -> dict[str, object]:
    """关键词图谱：节点为分组，边为同一篇论文内的共现。

    默认不把「未归类」画成节点：它与几乎所有节点都有共现、且规模恒等于分母，
    画出来会盖住真实主题；它的规模仍在 unmapped 字段中给出。
    """
    if limit <= 0:
        raise ApiError(400, "invalid_parameter", "limit 必须是正整数。")
    if min_edge <= 0:
        raise ApiError(400, "invalid_parameter", "min_edge 必须是正整数。")
    base = denominator(session, scope)
    group_names = _topic_group_names(session)

    # 一次取出范围内的 (论文, 分组) 对，随后在内存里按论文成对计数。
    # 1200 篇 × 每篇 ≤ MAX_PER_PAPER 条关系，规模可控；不构造稠密矩阵。
    params: dict[str, object] = {}
    clause = _scope_clause(scope, alias="ap", params=params)
    filter_unmapped = (
        " AND t.id IS NOT NULL" if exclude_unmapped and group_by == GROUP_BY_TOPIC else ""
    )
    rows = session.execute(
        text(
            f"SELECT ak.paper_id, {_group_projection(group_by)} "
            f"{_analysis_keyword_from(group_by)} "
            f"WHERE {clause}{filter_unmapped} "
            "GROUP BY ak.paper_id, group_key"
        ),
        params,
    ).all()

    node_counts: Counter[str] = Counter()
    node_labels: dict[str, str] = {}
    node_unmapped: dict[str, bool] = {}
    papers: dict[int, set[str]] = defaultdict(set)
    for paper_id, key, label, unmapped in rows:
        group_key = str(key)
        node_counts[group_key] += 1
        node_labels.setdefault(group_key, str(label))
        node_unmapped.setdefault(group_key, bool(unmapped))
        papers[int(paper_id)].add(group_key)

    edge_counts: Counter[tuple[str, str]] = Counter()
    for keys in papers.values():
        ordered = sorted(keys)
        for index, left in enumerate(ordered):
            for right in ordered[index + 1 :]:
                edge_counts[(left, right)] += 1

    ranked = sorted(node_counts.items(), key=lambda item: (-item[1], item[0]))
    nodes = [
        {
            "key": key,
            "name": node_labels.get(key, key),
            "group": None if group_by == GROUP_BY_KEYWORD else group_names.get(key),
            "is_unmapped": node_unmapped.get(key, False),
            "count": count,
        }
        for key, count in ranked[:limit]
    ]
    selected = {node["key"] for node in nodes}
    edges = [
        {
            "source": left,
            "target": right,
            "weight": weight,
            "source_name": node_labels.get(left, left),
            "target_name": node_labels.get(right, right),
        }
        for (left, right), weight in sorted(
            edge_counts.items(), key=lambda item: (-item[1], item[0][0], item[0][1])
        )
        if weight >= min_edge and left in selected and right in selected
    ]
    edge_total = sum(1 for weight in edge_counts.values() if weight >= min_edge)

    return {
        "scope": scope.describe(),
        "denominator": base,
        "total_sample": total_sample(session, scope),
        "excluded": excluded_counts(session, scope),
        "nodes": nodes,
        "edges": edges,
        "truncated": len(ranked) > len(nodes),
        "node_total": len(ranked),
        "edge_total": edge_total,
        "unmapped": _unmapped_block(session, scope, group_by),
        "exclude_unmapped": exclude_unmapped,
        "limit": limit,
        "min_edge": min_edge,
        "has_data": base > 0,
        "group_by": group_by,
    }


# ------------------------------------------------------------------ 趋势


def _year_axis(session: Session, scope: Scope) -> list[int]:
    """年份轴：范围内出现过的年份，从最早到最晚连续排列。

    范围内没有任何记录时（例如用户只选了库中未采样的会议年份），
    退回「全库年份范围」而不是返回空轴：空轴会让响应里连一个 has_data = false 的点都没有，
    反而看不出「这个组合没有被采集」，与「没有记录不等于该届没举办」的如实口径相悖。
    """
    params: dict[str, object] = {}
    clause = _scope_clause(scope, alias="p", params=params)
    row = session.execute(
        text(
            "SELECT MIN(p.year), MAX(p.year) FROM paper p "
            "WHERE p.conference IN ('CVPR', 'ICCV', 'ECCV') AND p.year > 0 "
            f"AND {clause}"
        ),
        params,
    ).first()
    if row is None or row[0] is None:
        row = session.execute(
            text(
                "SELECT MIN(p.year), MAX(p.year) FROM paper p "
                "WHERE p.conference IN ('CVPR', 'ICCV', 'ECCV') AND p.year > 0"
            )
        ).first()
    if row is None or row[0] is None:
        return []
    start, end = int(row[0]), int(row[1])
    # 年份轴不得超出调用方给的区间：否则只查某一年时会连带返回区间外的单元格
    if scope.year_from is not None:
        start = max(start, scope.year_from)
    if scope.year_to is not None:
        end = min(end, scope.year_to)
    if start > end:
        return []
    return list(range(start, end + 1))


def _records_per_cell(session: Session, scope: Scope) -> dict[tuple[str, int], int]:
    """每个 (会议, 年份) 的**记录数**，用于区分「没有记录」与「有样本但计数为 0」。"""
    params: dict[str, object] = {}
    clause = _scope_clause(scope, alias="p", params=params)
    rows = session.execute(
        text(
            "SELECT p.conference, p.year, COUNT(*) FROM paper p "
            "WHERE p.conference IN ('CVPR', 'ICCV', 'ECCV') AND p.year > 0 "
            f"AND {clause} GROUP BY 1, 2"
        ),
        params,
    ).all()
    return {(str(conference), int(year)): int(count) for conference, year, count in rows}


@_cached_response
def trend(
    session: Session,
    scope: Scope,
    *,
    keys: list[str] | None = None,
    limit_keys: int = STATS_TOP_LIMIT,
    group_by: str = GROUP_BY_TOPIC,
) -> dict[str, object]:
    """按会议与年份的趋势序列。

    未指定 keys 时取范围内占比最高的前 limit_keys 个分组，与 Top 榜同口径。
    """
    base = denominator(session, scope)
    years = _year_axis(session, scope)
    records = _records_per_cell(session, scope)
    group_names = _topic_group_names(session)

    params: dict[str, object] = {}
    clause = _scope_clause(scope, alias="ap", params=params)
    filter_unmapped = " AND t.id IS NOT NULL" if group_by == GROUP_BY_TOPIC else ""
    cell_rows = session.execute(
        text(
            f"SELECT {_group_projection(group_by)}, ap.conference, ap.year, "
            "COUNT(DISTINCT ak.paper_id) AS paper_count "
            f"{_analysis_keyword_from(group_by)} "
            f"WHERE {clause}{filter_unmapped} "
            "GROUP BY group_key, ap.conference, ap.year"
        ),
        params,
    ).all()

    cell_counts: dict[str, dict[tuple[str, int], int]] = defaultdict(dict)
    labels: dict[str, str] = {}
    for key, label, _unmapped, conference, year, count in cell_rows:
        group_key = str(key)
        labels.setdefault(group_key, str(label))
        cell_counts[group_key][(str(conference), int(year))] = int(count)

    cell_denominator = _cell_denominators(session, scope)
    if keys:
        wanted = [key.strip() for key in keys if key.strip()]
    else:
        ranked = sorted(
            cell_counts.items(),
            key=lambda item: (-sum(item[1].values()), item[0]),
        )
        wanted = [key for key, _ in ranked[:limit_keys]]

    series: list[dict[str, object]] = []
    for key in wanted:
        points: list[dict[str, object]] = []
        for conference in scope.conferences:
            for year in years:
                cell = (conference, year)
                cell_base = cell_denominator.get(cell, 0)
                has_records = records.get(cell, 0) > 0
                if not has_records:
                    # 该会议年份在本平台没有记录：不能据此判断该届是否举办
                    points.append(
                        {
                            "conference": conference,
                            "year": year,
                            "count": None,
                            "denominator": 0,
                            "share": None,
                            "has_data": False,
                            "reason": "no_records_in_sample",
                        }
                    )
                    continue
                count = cell_counts.get(key, {}).get(cell, 0)
                points.append(
                    {
                        "conference": conference,
                        "year": year,
                        "count": count,
                        "denominator": cell_base,
                        "share": _share(count, cell_base),
                        "has_data": cell_base > 0,
                        "reason": None if cell_base > 0 else "no_analysis_paper",
                    }
                )
        series.append(
            {
                "key": key,
                "name": labels.get(key, key),
                "group": None if group_by == GROUP_BY_KEYWORD else group_names.get(key),
                "is_unmapped": key == UNMAPPED_KEY,
                "points": points,
            }
        )

    return {
        "scope": scope.describe(),
        "denominator": base,
        "total_sample": total_sample(session, scope),
        "excluded": excluded_counts(session, scope),
        "keys": wanted,
        "key_total": _key_total(session, scope, group_by),
        "unmapped": _unmapped_block(session, scope, group_by),
        "years": years,
        "conferences": list(scope.conferences),
        "series": series,
        "coverage": _coverage(session),
        "has_data": base > 0,
        "group_by": group_by,
    }


def _cell_denominators(
    session: Session, scope: Scope
) -> dict[tuple[str, int], int]:
    """每个 (会议, 年份) 的分析集合分母。"""
    params: dict[str, object] = {}
    clause = _scope_clause(scope, alias="ap", params=params)
    rows = session.execute(
        text(
            "SELECT ap.conference, ap.year, COUNT(*) FROM v_analysis_paper ap "
            f"WHERE {clause} GROUP BY 1, 2"
        ),
        params,
    ).all()
    return {(str(conference), int(year)): int(count) for conference, year, count in rows}


# ------------------------------------------------------------------ 数据覆盖


def coverage_detail(session: Session) -> dict[str, object]:
    """数据覆盖明细：每个会议年份的记录数、分析分母、关键词状态与来源分布。

    与统计口径共用同一套有效性规则（分析集合来自 v_analysis_paper），
    但**记录数**统计的是库中全部行（含待处理与失败），用于说明样本量而非分母。
    """
    rows = session.execute(
        text(
            """
            SELECT p.conference AS conference,
                   p.year AS year,
                   COUNT(*) AS records,
                   SUM(CASE WHEN p.abstract_status = 'present' THEN 1 ELSE 0 END)
                     AS abstract_present,
                   SUM(CASE WHEN p.keyword_status = 'done' THEN 1 ELSE 0 END)
                     AS keyword_done,
                   SUM(CASE WHEN p.keyword_status = 'pending' THEN 1 ELSE 0 END)
                     AS keyword_pending,
                   SUM(CASE WHEN p.keyword_status = 'failed' THEN 1 ELSE 0 END)
                     AS keyword_failed
              FROM paper p
             WHERE p.conference IN ('CVPR', 'ICCV', 'ECCV') AND p.year > 0
             GROUP BY p.conference, p.year
             ORDER BY p.conference, p.year
            """
        )
    ).all()
    analysis_rows = session.execute(
        text(
            "SELECT conference, year, COUNT(*) FROM v_analysis_paper "
            "GROUP BY conference, year"
        )
    ).all()
    analysis_by_cell = {
        (str(conference), int(year)): int(count)
        for conference, year, count in analysis_rows
    }
    covered = [
        {
            "conference": str(row[0]),
            "year": int(row[1]),
            "records": int(row[2]),
            "analysis_papers": analysis_by_cell.get((str(row[0]), int(row[1])), 0),
            "abstract_present": int(row[3] or 0),
            "keyword_done": int(row[4] or 0),
            "keyword_pending": int(row[5] or 0),
            "keyword_failed": int(row[6] or 0),
        }
        for row in rows
    ]

    # 论文的来源标识分布：说明数据「从哪来」，与来源页面一一对应
    source_rows = session.execute(
        text(
            "SELECT source, COUNT(DISTINCT paper_id) FROM paper_source "
            "GROUP BY source ORDER BY COUNT(DISTINCT paper_id) DESC"
        )
    ).all()
    by_source = [
        {"source": str(source), "papers": int(count)} for source, count in source_rows
    ]

    total_records = sum(item["records"] for item in covered)  # type: ignore[arg-type]
    total_analysis = sum(item["analysis_papers"] for item in covered)  # type: ignore[arg-type]
    coverage = _coverage(session)
    return {
        "conferences": list(CONFERENCES),
        "target_conference_years": [
            {"conference": conference, "year": year}
            for conference, year in TARGET_CONFERENCE_YEARS
        ],
        "covered": covered,
        "missing_conference_years": coverage["missing_conference_years"],
        "totals": {
            "records": total_records,
            "analysis_papers": total_analysis,
            "conference_years": len(covered),
        },
        "sampled": coverage["sampled"],
        "sample_limit_per_conference_year": coverage["sample_limit_per_conference_year"],
        "sample_basis": coverage["sample_basis"],
        "by_source": by_source,
        "data_updated_at": _now_updated_at(session),
        "keyword_ruleset_version": _current_ruleset(session),
        "topic_ruleset_version": _topic_ruleset(session),
        "has_data": total_analysis > 0,
    }


def _topic_ruleset(session: Session) -> str:
    """当前主题表版本（meta 由 initialize_database 同步自代码常量）。"""
    row = session.get(AppMeta, "topic_ruleset_version")
    return row.value if row is not None and row.value else ""


# ------------------------------------------------------------------ 概览


@_cached_response
def summary(
    session: Session, scope: Scope, *, group_by: str = GROUP_BY_TOPIC
) -> dict[str, object]:
    """首页概览：分母、热点、未归类数量、排除量、覆盖情况与数据更新时间。"""
    base = denominator(session, scope)
    group_names = _topic_group_names(session)

    params: dict[str, object] = {}
    clause = _scope_clause(scope, alias="ap", params=params)
    keyword_total = int(
        session.execute(
            text(
                "SELECT COUNT(DISTINCT ak.keyword_id) "
                "FROM v_analysis_keyword ak "
                "JOIN v_analysis_paper ap ON ap.id = ak.paper_id "
                f"WHERE {clause}"
            ),
            params,
        ).scalar_one()
    )
    # 未归类数量同样限定在范围内，与榜单同一口径
    unmapped_total = int(
        session.execute(
            text(
                "SELECT COUNT(DISTINCT ak.keyword_id) "
                "FROM v_analysis_keyword ak "
                "JOIN v_analysis_paper ap ON ap.id = ak.paper_id "
                "JOIN keyword k ON k.id = ak.keyword_id "
                f"WHERE {clause} AND k.topic_id IS NULL"
            ),
            params,
        ).scalar_one()
    )

    hottest_rows = _top_rows(session, scope, group_by, 1)
    hottest = None
    if hottest_rows:
        key, label, _unmapped, count = hottest_rows[0]
        hottest = {
            "key": key,
            "name": label,
            "group": None if group_by == GROUP_BY_KEYWORD else group_names.get(key),
            "count": count,
            "share": _share(count, base),
        }

    return {
        "scope": scope.describe(),
        "denominator": base,
        "total_sample": total_sample(session, scope),
        "keyword_total": keyword_total,
        "hottest": hottest,
        "unmapped_keyword_total": unmapped_total,
        "unmapped": _unmapped_block(session, scope, group_by),
        "excluded": excluded_counts(session, scope),
        "coverage": _coverage(session),
        "data_updated_at": _now_updated_at(session),
        # 年份轴：界面用它构造年份区间选择器，取值来自库中实际存在的记录
        "years": _year_axis(session, scope),
        "analysis_version": read_analysis_version(session),
        "keyword_ruleset_version": _current_ruleset(session),
        "has_data": base > 0,
        "group_by": group_by,
    }
