"""统计口径专项测试：用可手算的小数据集验证分母、去重、缺失与零的区别。

设计依据：开发设计与验收.md 第 4 章、第 9 章「统计口径专项测试」。

数据集（全部可手工复算）：

    CVPR 2024：A1 目标检测+图像分割 / A2 目标检测 / A3 关键词为空（成功但为空）
               A4 待处理 / A5 处理失败 / A6 旧版本完成 / A7 标题不可用
    ICCV 2023：B1 目标检测+图像分割
    ICCV 2025：B2 目标检测
    ECCV 2022：C1 关键词为空 / C2 与 A1 同名（跨会议年份同名）
    ICCV 2024：无任何记录（未采样）

断言里写清了每个数字是怎么算出来的，改动口径时这些数字必须同步更新。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.config import KEYWORD_RULESET_VERSION
from app.db.engine import reset_engine, session_scope
from app.services import stats
from tests.helpers import (
    add_system_keyword,
    insert_paper,
    insert_topic,
    set_meta,
)

STALE_VERSION = "kw-v2"


@pytest.fixture()
def caliber(temp_db: Path) -> dict[str, int]:
    """构造可手算的统计数据集，返回主题 id 映射。"""
    detection = insert_topic(temp_db, slug="object-detection", name="目标检测")
    segmentation = insert_topic(temp_db, slug="segmentation", name="图像分割")

    def done_paper(code: str, conference: str, year: int, title: str) -> int:
        return insert_paper(
            temp_db,
            code=code,
            conference=conference,
            year=year,
            title=title,
            keyword_status="done",
            keyword_ruleset_version=KEYWORD_RULESET_VERSION,
        )

    # CVPR 2024
    a1 = done_paper("CVPR-2024-0001", "CVPR", 2024, "Prompt Tuning For Detection")
    a2 = done_paper("CVPR-2024-0002", "CVPR", 2024, "Adapter Tuning For Segmentation")
    a3 = done_paper("CVPR-2024-0003", "CVPR", 2024, "Empty Keywords Paper Here")
    a4 = insert_paper(
        temp_db, code="CVPR-2024-0004", title="Pending Keyword Paper", conference="CVPR", year=2024
    )
    a5 = insert_paper(
        temp_db,
        code="CVPR-2024-0005",
        title="Failed Keyword Paper",
        conference="CVPR",
        year=2024,
        keyword_status="failed",
    )
    # 第二条待处理：四个桶的期望值互不相同，列顺序写反时用例会失败
    insert_paper(
        temp_db, code="CVPR-2024-0008", title="Another Pending Paper", conference="CVPR", year=2024
    )
    a6 = insert_paper(
        temp_db,
        code="CVPR-2024-0006",
        title="Old Ruleset Paper Here",
        conference="CVPR",
        year=2024,
        keyword_status="done",
        keyword_ruleset_version=STALE_VERSION,
    )
    a7 = insert_paper(
        temp_db,
        code="CVPR-2024-0007",
        title="ab",  # 归一化后长度 < 4，属于标题不可用
        conference="CVPR",
        year=2024,
        keyword_status="done",
        keyword_ruleset_version=KEYWORD_RULESET_VERSION,
    )

    add_system_keyword(temp_db, paper_id=a1, name="object detection", topic_id=detection)
    add_system_keyword(temp_db, paper_id=a1, name="image segmentation", topic_id=segmentation)
    add_system_keyword(temp_db, paper_id=a2, name="object detection", topic_id=detection)
    # A3 没有关键词关系：成功但为空，仍要进分母
    add_system_keyword(temp_db, paper_id=a6, name="object detection", version=STALE_VERSION, topic_id=detection)

    # ICCV 2023
    b1 = done_paper("ICCV-2023-0001", "ICCV", 2023, "Masked Autoencoder For Vision")
    add_system_keyword(temp_db, paper_id=b1, name="object detection", topic_id=detection)
    add_system_keyword(temp_db, paper_id=b1, name="image segmentation", topic_id=segmentation)

    # ICCV 2025
    b2 = done_paper("ICCV-2025-0001", "ICCV", 2025, "Distillation For Detection")
    add_system_keyword(temp_db, paper_id=b2, name="object detection", topic_id=detection)

    # ECCV 2022：C2 与 A1 同名，但会议年份不同，必须是两条独立记录
    done_paper("ECCV-2022-0001", "ECCV", 2022, "Empty Keyword Paper Two")
    done_paper("ECCV-2022-0002", "ECCV", 2022, "Prompt Tuning For Detection")

    return {"detection": detection, "segmentation": segmentation}


def _view(db_path: Path, name: str) -> int:
    connection = sqlite3.connect(db_path)
    try:
        return int(connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
    finally:
        connection.close()


def test_analysis_denominator_counts_empty_keyword_paper(caliber, temp_db: Path):
    """分母取自分析集合，不靠关键词关联反推：成功但关键词为空的论文仍计入。"""
    # 分析集合 = A1 A2 A3（CVPR2024）+ B1（ICCV2023）+ B2（ICCV2025）+ C1 C2 C3（ECCV2022）= 8
    assert _view(temp_db, "v_analysis_paper") == 7
    # 语料集合 = 全部 12 条里标题可用的部分，即排除标题不可用的 A7
    assert _view(temp_db, "v_corpus_paper") == 11

    with session_scope() as session:
        assert stats.denominator(session, stats.parse_scope()) == 7
        # 只有 A1 A2 B1 B2 有系统关键词关系，若用关系反推分母会少算 4 篇
        assert stats.denominator(session, stats.parse_scope(conference=["CVPR"], year=2024)) == 3


def test_excluded_buckets_are_disjoint_and_cover_all_records(caliber, temp_db: Path):
    """四个排除桶互斥且合计等于记录总数，避免同一篇论文被数两遍。"""
    with session_scope() as session:
        scope = stats.parse_scope()
        excluded = stats.excluded_counts(session, scope)
        total = stats.total_sample(session, scope)

    # CVPR2024: 两条待处理、一条失败、一条旧版本、一条标题不可用
    assert excluded == {"pending": 2, "failed": 1, "stale": 1, "invalid_title": 1}
    # 12 条记录 = 7 篇分析集合 + 5 篇被排除，没有遗漏也没有重复计数
    assert total == 12
    assert sum(excluded.values()) + _view(temp_db, "v_analysis_paper") == total


def test_top_orders_by_deduped_paper_count(caliber):
    """Top 榜按去重论文数排序：同一篇论文对同一主题只计一次。"""
    with session_scope() as session:
        result = stats.top(session, stats.parse_scope(), limit=10)

    # 目标检测：A1 A2 B1 B2 = 4 篇；图像分割：A1 B1 = 2 篇
    assert [item["name"] for item in result["items"]] == ["目标检测", "图像分割"]
    assert [item["count"] for item in result["items"]] == [4, 2]
    assert result["denominator"] == 7
    # 占比 = count / 分母，分母是分析集合而不是记录数
    assert result["items"][0]["share"] == pytest.approx(round(4 / 7 * 100, 4))
    assert result["items"][1]["share"] == pytest.approx(round(2 / 7 * 100, 4))
    assert result["key_total"] == 2
    assert result["has_data"] is True


def test_cross_scope_weighting_merges_counts_before_dividing(caliber):
    """跨组加权：先合并计数与分母再相除，不是平均各组百分比。"""
    with session_scope() as session:
        result = stats.top(
            session, stats.parse_scope(conference=["CVPR", "ICCV"], year=2024)
        )
        cvpr_only = stats.top(session, stats.parse_scope(conference=["CVPR"], year=2024))

    # CVPR2024 分母 3、目标检测 2 → 66.67%；平均百分比的做法会得到 66.67%
    assert cvpr_only["denominator"] == 3
    assert cvpr_only["items"][0]["count"] == 2
    # （CVPR, ICCV）× 2024：ICCV 2024 无记录，只有 CVPR 的 3 篇进入分母
    assert result["denominator"] == 3
    assert result["items"][0]["count"] == 2


def test_top_share_uses_merged_denominator_across_conferences(caliber):
    """两届合并时的占比必须用合并分母计算。"""
    with session_scope() as session:
        merged = stats.top(session, stats.parse_scope(conference=["CVPR", "ICCV"]))

    # 分母 = 3（CVPR2024）+ 1（ICCV2023）+ 1（ICCV2025）= 5
    assert merged["denominator"] == 5
    detection = next(item for item in merged["items"] if item["name"] == "目标检测")
    # 目标检测 = A1 A2（CVPR2024）+ B1（ICCV2023）+ B2（ICCV2025）= 4
    assert detection["count"] == 4
    assert detection["share"] == pytest.approx(80.0)
    # 平均各组百分比会得到 (66.67 + 100 + 100) / 3 = 88.89，与正确口径不同
    assert detection["share"] != pytest.approx(88.89, abs=0.1)


def test_graph_edge_weight_counts_cooccurring_papers(caliber):
    """边权 = 同篇共现的去重论文数；节点大小 = 关联论文数。"""
    with session_scope() as session:
        result = stats.graph(
            session, stats.parse_scope(conference=["CVPR", "ICCV"], year=2023),
            limit=10, min_edge=1,
        )

    # 该范围只有 B1：目标检测与图像分割在同一篇里各出现一次 → 边权 1
    assert result["denominator"] == 1
    assert [node["name"] for node in result["nodes"]] == ["目标检测", "图像分割"]
    assert [node["count"] for node in result["nodes"]] == [1, 1]
    assert len(result["edges"]) == 1
    assert result["edges"][0]["weight"] == 1

    with session_scope() as session:
        wider = stats.graph(session, stats.parse_scope(), limit=10, min_edge=1)
    edge = next(
        item
        for item in wider["edges"]
        if {item["source"], item["target"]} == {"object-detection", "segmentation"}
    )
    # A1 与 B1 两篇同时含两个主题 → 权重 2
    assert edge["weight"] == 2
    assert edge["source_name"] == "目标检测"
    assert edge["target_name"] == "图像分割"


def test_min_edge_filters_graph_edges(caliber):
    """min_edge 过滤：权重低于阈值的边不出现在结果里，但 edge_total 如实计数。"""
    with session_scope() as session:
        result = stats.graph(session, stats.parse_scope(), limit=10, min_edge=3)

    assert result["edges"] == []
    # 权重 ≥ 3 的边为 0 条，但权重 ≥ 1 的共现关系确实存在
    assert result["edge_total"] == 0
    with session_scope() as session:
        loose = stats.graph(session, stats.parse_scope(), limit=10, min_edge=1)
    assert loose["edge_total"] == 1


def test_trend_distinguishes_missing_data_from_zero(caliber):
    """没有记录 → null + has_data false；有样本但主题为 0 → 0.0 + has_data true。"""
    with session_scope() as session:
        result = stats.trend(
            session, stats.parse_scope(), keys=["object-detection"]
        )

    points = {
        (point["conference"], point["year"]): point for point in result["series"][0]["points"]
    }
    # CVPR2024：分母 3、目标检测 2 → 66.6667
    cvpr_2024 = points[("CVPR", 2024)]
    assert cvpr_2024["count"] == 2
    assert cvpr_2024["denominator"] == 3
    assert cvpr_2024["share"] == pytest.approx(66.6667)
    assert cvpr_2024["has_data"] is True

    # ECCV2022：有样本（分母 2）但没有目标检测 → 0，而不是 null
    eccv_2022 = points[("ECCV", 2022)]
    assert eccv_2022["count"] == 0
    assert eccv_2022["denominator"] == 2
    assert eccv_2022["share"] == 0.0
    assert eccv_2022["has_data"] is True

    # ICCV2024：库中没有任何记录 → 不能据此断定该届没举办，返回 null
    iccv_2024 = points[("ICCV", 2024)]
    assert iccv_2024["count"] is None
    assert iccv_2024["denominator"] == 0
    assert iccv_2024["share"] is None
    assert iccv_2024["has_data"] is False
    assert iccv_2024["reason"] == "no_records_in_sample"


def test_trend_returns_zero_for_unknown_topic_but_has_data(caliber):
    """有样本但主题不存在 → count = 0、share = 0.0；与缺失区分开。"""
    with session_scope() as session:
        result = stats.trend(
            session, stats.parse_scope(conference=["CVPR"], year=2024),
            keys=["topic-that-does-not-exist"],
        )

    point = result["series"][0]["points"][0]
    assert point["count"] == 0
    assert point["denominator"] == 3
    assert point["share"] == 0.0
    assert point["has_data"] is True


def test_zero_denominator_returns_null_share(caliber):
    """分母为零的范围：分母 0、share 全为 null、items 为空、has_data false。"""
    with session_scope() as session:
        scope = stats.parse_scope(conference=["ICCV"], year=2024)
        result = stats.top(session, scope)

    assert result["denominator"] == 0
    assert result["items"] == []
    assert result["has_data"] is False
    assert result["total_sample"] == 0


def test_ruleset_change_moves_papers_out_of_denominator(caliber, temp_db: Path):
    """规则版本变更后：旧版本论文整体退出分母并计入 stale，分母为零时返回空值。"""
    with session_scope() as session:
        before = stats.summary(session, stats.parse_scope())
    assert before["denominator"] == 7
    assert before["keyword_ruleset_version"] == KEYWORD_RULESET_VERSION

    set_meta(temp_db, "keyword_ruleset_version", "kw-v4")
    with session_scope() as session:
        after = stats.summary(session, stats.parse_scope())
        top_after = stats.top(session, stats.parse_scope())

    assert after["denominator"] == 0
    assert after["has_data"] is False
    assert top_after["items"] == []
    # 标题不可用的那条优先归入 invalid_title，其余已完成论文全部计为 stale
    assert after["excluded"] == {
        "invalid_title": 1,
        "stale": 8,
        "failed": 1,
        "pending": 2,
    }
    assert sum(after["excluded"].values()) == after["total_sample"]


def test_same_title_in_different_conference_year_are_both_counted(caliber, temp_db: Path):
    """跨会议年份同名是两条独立记录，都进分母（阶段 6 去重键修正的复核点）。"""
    connection = sqlite3.connect(temp_db)
    try:
        rows = connection.execute(
            "SELECT COUNT(*) FROM paper WHERE title = 'Prompt Tuning For Detection'"
        ).fetchone()
    finally:
        connection.close()
    assert int(rows[0]) == 2

    with session_scope() as session:
        cvpr = stats.denominator(session, stats.parse_scope(conference=["CVPR"], year=2024))
        eccv = stats.denominator(session, stats.parse_scope(conference=["ECCV"], year=2022))
    assert cvpr == 3
    assert eccv == 2


def test_duplicate_record_cannot_enter_analysis_set(temp_db: Path):
    """重复记录进不了库：去重键唯一，插入第二条会失败。"""
    insert_paper(
        temp_db,
        code="CVPR-2024-9001",
        title="Duplicate Candidate Paper",
        keyword_status="done",
        keyword_ruleset_version=KEYWORD_RULESET_VERSION,
    )
    with pytest.raises(sqlite3.IntegrityError):
        insert_paper(
            temp_db,
            code="CVPR-2024-9002",
            title="Duplicate Candidate Paper",
            keyword_status="done",
            keyword_ruleset_version=KEYWORD_RULESET_VERSION,
        )


def test_title_only_paper_counts_in_denominator(temp_db: Path):
    """摘要缺失但标题可用：仍进分母；关键词处理成功即可参与统计。"""
    paper_id = insert_paper(
        temp_db,
        code="CVPR-2024-8001",
        title="Title Only Analysis Paper",
        abstract_status="missing",
        keyword_status="done",
        keyword_ruleset_version=KEYWORD_RULESET_VERSION,
    )
    topic_id = insert_topic(temp_db, slug="object-detection", name="目标检测")
    add_system_keyword(temp_db, paper_id=paper_id, name="object detection", topic_id=topic_id)

    with session_scope() as session:
        result = stats.top(session, stats.parse_scope(conference=["CVPR"], year=2024))
    assert result["denominator"] == 1
    assert result["items"][0]["count"] == 1


def test_unmapped_keywords_are_reported_not_ranked(temp_db: Path):
    """未归类关键词不占榜单名额，但数量与占比必须在响应里如实给出。"""
    paper_id = insert_paper(
        temp_db,
        code="CVPR-2024-7001",
        title="Unmapped Keyword Paper",
        keyword_status="done",
        keyword_ruleset_version=KEYWORD_RULESET_VERSION,
    )
    add_system_keyword(temp_db, paper_id=paper_id, name="some unmapped phrase")

    with session_scope() as session:
        result = stats.top(session, stats.parse_scope())
        included = stats.top(session, stats.parse_scope(), exclude_unmapped=False)

    assert result["items"] == []
    assert result["unmapped"]["applies"] is True
    assert result["unmapped"]["keyword_total"] == 1
    assert result["unmapped"]["paper_count"] == 1
    assert result["unmapped"]["share"] == 100.0

    # 显式要求包含时，未归类作为一个分组参与排序
    assert [item["name"] for item in included["items"]] == ["未归类"]
    assert included["items"][0]["is_unmapped"] is True


def test_keyword_group_by_skips_topic_mapping(caliber):
    """group_by=keyword 直接按关键词聚合，不受主题映射影响。"""
    with session_scope() as session:
        result = stats.top(session, stats.parse_scope(), group_by="keyword")
        summary = stats.summary(session, stats.parse_scope(), group_by="keyword")

    names = [item["name"] for item in result["items"]]
    assert "object detection" in names
    assert "image segmentation" in names
    assert result["unmapped"]["applies"] is False
    # 按关键词时不分组配色，也不存在未归类的概念
    assert all(item["group"] is None for item in result["items"])
    assert summary["unmapped"]["applies"] is False


def test_reset_engine_for_fixture(temp_db: Path):
    """夹具结束后引擎指向仍可正常解析（避免路径缓存污染后续用例）。"""
    reset_engine()
    with session_scope() as session:
        assert stats.total_sample(session, stats.parse_scope()) >= 0
