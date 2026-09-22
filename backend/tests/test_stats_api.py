"""统计与关键词维护接口的 HTTP 行为测试。

覆盖：参数校验、空值/零的口径在响应里可区分、榜单与图谱与趋势的一致性、
按需处理后的自动失效（不需要手动清缓存）、主题表重载链路。
"""

from __future__ import annotations

from pathlib import Path

from app.config import KEYWORD_RULESET_VERSION
from app.db.engine import session_scope
from app.services import topic_layer
from tests.helpers import add_system_keyword, insert_paper, insert_topic

ANALYSIS_PAPER = {
    "title": "Parameter Efficient Prompt Tuning For Vision",
    "conference": "CVPR",
    "year": 2024,
    "abstract": "We study prompt tuning for vision transformers in this paper. "
    "The method is evaluated on several benchmarks.",
}


def _create_paper(client, **overrides) -> dict:
    payload = {**ANALYSIS_PAPER, **overrides}
    response = client.post("/api/papers", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_summary_reports_pending_paper_as_excluded(client):
    """刚创建的论文关键词尚未处理：不进分母，单列在 excluded.pending。"""
    _create_paper(client)
    response = client.get("/api/stats/summary")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["denominator"] == 0
    assert body["total_sample"] == 1
    assert body["excluded"] == {
        "invalid_title": 0,
        "stale": 0,
        "failed": 0,
        "pending": 1,
    }
    assert body["has_data"] is False
    assert body["hottest"] is None
    # 分母为零时占比必须是 null，不能写成 0
    assert body["unmapped"]["share"] is None


def test_on_demand_processing_makes_stats_visible_without_manual_cache_clear(client):
    """按需处理之后再查统计：结果自动更新，调用方不需要手动清缓存。"""
    _create_paper(client)
    first = client.get("/api/stats/summary").json()
    assert first["denominator"] == 0

    processed = client.post("/api/keywords/process")
    assert processed.status_code == 200, processed.text
    body = processed.json()
    assert body["processed"] == 1
    assert body["failed"] == 0
    assert body["remaining"] == 0

    second = client.get("/api/stats/summary").json()
    # 处理成功（无论是否抽到关键词）都进入分母：这是「成功但为空仍计入」的接口级验证
    assert second["denominator"] == 1
    assert second["excluded"]["pending"] == 0
    assert second["has_data"] is True
    assert second["analysis_version"] > first["analysis_version"]
    # 处理后论文的系统关键词按当前规则版本落库
    assert second["keyword_ruleset_version"] == KEYWORD_RULESET_VERSION


def test_summary_cache_is_invalidated_by_paper_write(client):
    """论文写入后统计随之变化：总样本数与分析集合版本都要更新。"""
    first = client.get("/api/stats/summary").json()
    assert first["total_sample"] == 0

    _create_paper(client, title="A Second Paper For Cache Check")
    second = client.get("/api/stats/summary").json()
    assert second["total_sample"] == 1
    assert second["analysis_version"] > first["analysis_version"]


def test_top_ranks_topics_and_reports_unmapped(client, temp_db: Path):
    """榜单按主题聚合，未归类不占名次但数量可见；include 时作为分组参与排序。"""
    # 直接构造分析集合内的论文与关键词，避免依赖抽取结果的具体词
    paper_id = insert_paper(
        temp_db,
        code="CVPR-2024-0001",
        title="Object Detection With Transformers",
        keyword_status="done",
        keyword_ruleset_version=KEYWORD_RULESET_VERSION,
    )
    add_system_keyword(temp_db, paper_id=paper_id, name="object detection")
    add_system_keyword(temp_db, paper_id=paper_id, name="an unmapped term here")

    reload_response = client.post("/api/keywords/topics/reload")
    assert reload_response.status_code == 200, reload_response.text

    body = client.get("/api/stats/top").json()
    assert body["denominator"] == 1
    names = [item["name"] for item in body["items"]]
    assert names == ["目标检测"]
    assert body["items"][0]["count"] == 1
    assert body["items"][0]["share"] == 100.0
    assert body["unmapped"]["keyword_total"] == 1
    assert body["unmapped"]["paper_count"] == 1

    included = client.get("/api/stats/top", params={"exclude_unmapped": "false"}).json()
    assert {item["name"] for item in included["items"]} == {"目标检测", "未归类"}


def test_summary_hottest_never_reports_unmapped_group(client, temp_db: Path):
    """概览的「最热主题」不能是未归类：未归类恒等于分母，作为第一名自相矛盾。"""
    paper_id = insert_paper(
        temp_db,
        code="CVPR-2024-0001",
        title="Hottest Topic Paper For Stats",
        keyword_status="done",
        keyword_ruleset_version=KEYWORD_RULESET_VERSION,
    )
    add_system_keyword(temp_db, paper_id=paper_id, name="object detection")
    add_system_keyword(temp_db, paper_id=paper_id, name="well and truly unmapped term")
    client.post("/api/keywords/topics/reload")

    body = client.get("/api/stats/summary").json()
    assert body["hottest"]["name"] == "目标检测"
    assert body["hottest"]["count"] == 1
    # 未归类的规模仍然可见，只是不占「最热」位置
    assert body["unmapped"]["paper_count"] == 1


def test_top_rejects_invalid_parameters(client):
    cases = [
        ({"conference": "NIPS"}, "invalid_parameter"),
        ({"year_from": 2025, "year_to": 2024}, "invalid_parameter"),
        ({"year": 2024, "year_from": 2023}, "invalid_parameter"),
        ({"group_by": "venue"}, "invalid_parameter"),
        ({"limit": 0}, "invalid_parameter"),  # 越界参数由统一校验映射为 400
    ]
    for params, expected_code in cases:
        response = client.get("/api/stats/top", params=params)
        assert response.status_code == 400, (params, response.text)
        assert response.json()["detail"]["code"] == expected_code


def test_trend_returns_null_for_uncovered_conference_year(client, temp_db: Path):
    """未采集的会议年份返回 null 与 has_data=false，而不是 0。"""
    insert_paper(
        temp_db,
        code="CVPR-2024-0001",
        title="Covered Conference Year Paper",
        keyword_status="done",
        keyword_ruleset_version=KEYWORD_RULESET_VERSION,
    )
    response = client.get("/api/stats/trend", params={"conference": ["ICCV"], "year": 2024})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["denominator"] == 0
    assert body["has_data"] is False

    point = body["series"][0]["points"][0] if body["series"] else None
    if point is not None:
        assert point["share"] is None
        assert point["count"] is None
        assert point["has_data"] is False


def test_graph_reports_truncation_and_edge_totals(client, temp_db: Path):
    """图谱如实回报截断与总量，min_edge 只影响返回的边。"""
    version = KEYWORD_RULESET_VERSION
    first = insert_paper(
        temp_db,
        code="CVPR-2024-0001",
        title="Graph Paper One For Stats",
        keyword_status="done",
        keyword_ruleset_version=version,
    )
    second = insert_paper(
        temp_db,
        code="CVPR-2024-0002",
        title="Graph Paper Two For Stats",
        keyword_status="done",
        keyword_ruleset_version=version,
    )
    left = insert_topic(temp_db, slug="left-topic", name="左主题")
    right = insert_topic(temp_db, slug="right-topic", name="右主题")
    for paper_id in (first, second):
        add_system_keyword(temp_db, paper_id=paper_id, name="left keyword", topic_id=left)
        add_system_keyword(temp_db, paper_id=paper_id, name="right keyword", topic_id=right)

    body = client.get("/api/stats/graph", params={"limit": 1, "min_edge": 1}).json()
    assert body["node_total"] == 2
    assert body["truncated"] is True
    assert len(body["nodes"]) == 1
    # 节点被截断后，两端不都在节点集合内的边不返回
    assert body["edges"] == []
    assert body["edge_total"] == 1

    loose = client.get("/api/stats/graph", params={"limit": 10, "min_edge": 1}).json()
    assert len(loose["edges"]) == 1
    assert loose["edges"][0]["weight"] == 2
    assert loose["truncated"] is False


def test_keywords_status_endpoint_reports_processing_state(client, temp_db: Path):
    """状态接口给出待处理量与主题映射覆盖，供维护界面使用。"""
    _create_paper(client)
    body = client.get("/api/keywords/status").json()
    assert body["corpus_papers"] == 1
    assert body["analysis_papers"] == 0
    assert body["pending_or_stale"] == 1
    assert body["by_status"] == {"pending": 1}
    assert body["mapped_keywords"] == 0


def test_topics_reload_loads_versioned_file_and_maps_keywords(client, temp_db: Path):
    """主题表重载：从版本化文件写入主题与别名，并把已有系统关键词映射过去。"""
    version = KEYWORD_RULESET_VERSION
    paper_id = insert_paper(
        temp_db,
        code="CVPR-2024-0001",
        title="Topic Mapping Paper For Stats",
        keyword_status="done",
        keyword_ruleset_version=version,
    )
    add_system_keyword(temp_db, paper_id=paper_id, name="object detection")
    add_system_keyword(temp_db, paper_id=paper_id, name="semantic segmentation")

    body = client.post("/api/keywords/topics/reload").json()
    assert body["topic_version"].startswith("topic-v")
    assert body["topics"] >= 30
    assert body["mapped_keywords"] == 2

    # 重载是幂等的：第二次不会重复新增主题
    again = client.post("/api/keywords/topics/reload").json()
    assert again["created"] == 0
    assert again["mapped_keywords"] == 2

    top = client.get("/api/stats/top").json()
    assert {item["name"] for item in top["items"]} == {"目标检测", "图像分割"}


def test_scope_filters_are_applied_consistently_across_endpoints(client, temp_db: Path):
    """总览、榜单、图谱、趋势使用相同筛选：分母与条目在四处一致。"""
    version = KEYWORD_RULESET_VERSION
    inside = insert_paper(
        temp_db,
        code="CVPR-2024-0001",
        title="Inside Scope Paper For Stats",
        keyword_status="done",
        keyword_ruleset_version=version,
    )
    insert_paper(
        temp_db,
        code="ECCV-2022-0001",
        title="Outside Scope Paper For Stats",
        conference="ECCV",
        year=2022,
        keyword_status="done",
        keyword_ruleset_version=version,
    )
    topic_id = insert_topic(temp_db, slug="inside-topic", name="范围内的主题")
    add_system_keyword(
        temp_db, paper_id=inside, name="inside keyword", topic_id=topic_id
    )

    params = {"conference": ["CVPR"], "year_from": 2024, "year_to": 2024}
    summary = client.get("/api/stats/summary", params=params).json()
    top = client.get("/api/stats/top", params=params).json()
    graph = client.get("/api/stats/graph", params=params).json()
    trend = client.get("/api/stats/trend", params=params).json()

    assert summary["denominator"] == top["denominator"] == 1
    assert graph["denominator"] == 1
    assert trend["denominator"] == 1
    assert summary["hottest"]["name"] == "范围内的主题"
    assert top["items"][0]["count"] == 1
    assert graph["nodes"][0]["count"] == 1
    assert summary["total_sample"] == top["total_sample"] == graph["total_sample"]


def test_coverage_endpoint_reports_empty_database(client):
    """空库：覆盖为空、无数据，但字段齐全（不返回 null 结构）。"""
    body = client.get("/api/stats/coverage").json()
    assert body["covered"] == []
    assert body["totals"] == {"records": 0, "analysis_papers": 0, "conference_years": 0}
    assert body["has_data"] is False
    assert body["by_source"] == []
    assert len(body["target_conference_years"]) == 6
    assert body["missing_conference_years"] == body["target_conference_years"]


def test_coverage_endpoint_counts_records_and_denominator_separately(client, temp_db: Path):
    """记录数与分析分母分开统计：待处理的记录进 records 但不进分母。"""
    version = KEYWORD_RULESET_VERSION
    insert_paper(
        temp_db,
        code="CVPR-2024-0001",
        title="Coverage Done Paper For Tests",
        keyword_status="done",
        keyword_ruleset_version=version,
    )
    insert_paper(
        temp_db,
        code="CVPR-2024-0002",
        title="Coverage Pending Paper For Tests",
    )
    from tests.helpers import connect

    with connect(temp_db) as connection:
        connection.execute(
            "INSERT INTO paper_source (paper_id, source, source_id, retrieved_at)"
            " SELECT id, 'cvf', code, '2026-01-01T00:00:00Z' FROM paper"
        )

    body = client.get("/api/stats/coverage").json()
    assert body["totals"]["records"] == 2
    assert body["totals"]["analysis_papers"] == 1
    cell = next(
        item
        for item in body["covered"]
        if item["conference"] == "CVPR" and item["year"] == 2024
    )
    assert cell["records"] == 2
    assert cell["analysis_papers"] == 1
    assert cell["keyword_pending"] == 1
    assert body["by_source"] == [{"source": "cvf", "papers": 2}]
    assert body["sampled"] is False
    assert body["sample_basis"] == "unknown"
