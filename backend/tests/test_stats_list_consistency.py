"""统计页跳转论文列表的口径一致性测试（开发设计与验收.md 第 7.5 节）。

统计的分子只算「系统关键词 + 当前规则版本 + 分析集合」，普通列表检索不带这些约束，
因此同一关键词的条数原本会比统计给出的数字多。这里锁定带 `from_stats` 时的收敛结果：
列表条数必须等于统计计数，并且回显实际生效的约束。
"""

from __future__ import annotations

from pathlib import Path

from app.config import KEYWORD_RULESET_VERSION
from app.db.engine import session_scope
from app.services import stats
from tests.helpers import (
    add_system_keyword,
    insert_paper,
    insert_topic,
    link_keyword,
    upsert_keyword,
)


def _dataset(db_path: Path) -> dict[str, int]:
    """三篇论文：一篇当前版本系统关键词、一篇旧版本、一篇作者关键词。"""
    topic_id = insert_topic(db_path, slug="object-detection", name="目标检测")
    current = insert_paper(
        db_path,
        code="CVPR-2024-0001",
        title="Current Version System Keyword Paper",
        keyword_status="done",
        keyword_ruleset_version=KEYWORD_RULESET_VERSION,
    )
    stale = insert_paper(
        db_path,
        code="CVPR-2024-0002",
        title="Stale Version Keyword Paper Here",
        keyword_status="done",
        keyword_ruleset_version="kw-v2",
    )
    author_only = insert_paper(
        db_path,
        code="CVPR-2024-0003",
        title="Author Keyword Only Paper Here",
        keyword_status="done",
        keyword_ruleset_version=KEYWORD_RULESET_VERSION,
    )
    add_system_keyword(
        db_path, paper_id=current, name="object detection", topic_id=topic_id
    )
    # 旧版本关系：统计看不到，普通检索能看到——正是需要被约束掉的那部分
    add_system_keyword(
        db_path,
        paper_id=stale,
        name="object detection",
        version="kw-v2",
        topic_id=topic_id,
    )
    author_keyword_id = upsert_keyword(db_path, name="目标检测", origin="author")
    link_keyword(db_path, paper_id=author_only, keyword_id=author_keyword_id)

    # 不调用 map_keywords_to_topics：临时库里没有别名表，重算映射会把上面
    # 直接设置好的 topic_id 清成 NULL（真实系统由别名表驱动映射）
    return {"topic_id": topic_id, "current": current}


def test_plain_list_is_wider_than_stats_count(client, temp_db: Path):
    """不带约束时列表条数会多于统计计数：这正是统计页跳转需要修正的差异。"""
    _dataset(temp_db)

    plain = client.get(
        "/api/papers", params={"keyword": "object detection", "page_size": 50}
    ).json()
    # 普通检索：当前版本 1 篇 + 旧版本 1 篇
    assert plain["total"] == 2
    assert plain["stats_mode"] is None

    with session_scope() as session:
        top = stats.top(session, stats.parse_scope(), limit=10)
    detection = next(item for item in top["items"] if item["name"] == "目标检测")
    # 统计只看当前版本：1 篇
    assert detection["count"] == 1


def test_from_stats_list_matches_stats_count(client, temp_db: Path):
    """带 from_stats 时列表条数必须等于统计计数。"""
    _dataset(temp_db)

    scoped = client.get(
        "/api/papers",
        params={"keyword": "object detection", "from_stats": "true", "page_size": 50},
    ).json()
    assert scoped["total"] == 1
    assert scoped["stats_mode"] == {
        "keyword_origin": "system",
        "ruleset_version": KEYWORD_RULESET_VERSION,
        "in_analysis_set": True,
    }
    assert scoped["items"][0]["code"] == "CVPR-2024-0001"


def test_topic_filter_with_from_stats_matches_stats_count(client, temp_db: Path):
    """按主题跳转时同样对得上：主题条数 = 统计给出的主题计数。"""
    _dataset(temp_db)

    with session_scope() as session:
        top = stats.top(session, stats.parse_scope(), limit=10)
    detection = next(item for item in top["items"] if item["name"] == "目标检测")

    listed = client.get(
        "/api/papers",
        params={"topic": "object-detection", "from_stats": "true", "page_size": 50},
    ).json()
    assert listed["total"] == detection["count"]


def test_author_keyword_hit_is_excluded_in_stats_mode(client, temp_db: Path):
    """作者关键词命中在统计口径下被排除（统计只算系统关键词）。"""
    _dataset(temp_db)

    plain = client.get(
        "/api/papers", params={"keyword": "目标检测", "page_size": 50}
    ).json()
    assert plain["total"] == 1

    scoped = client.get(
        "/api/papers",
        params={"keyword": "目标检测", "from_stats": "true", "page_size": 50},
    ).json()
    assert scoped["total"] == 0


def test_in_analysis_set_param_can_be_used_alone(client, temp_db: Path):
    """三个约束也可以单独显式使用，便于排查某个约束的影响。"""
    _dataset(temp_db)

    analysis_only = client.get(
        "/api/papers", params={"in_analysis_set": "true", "page_size": 50}
    ).json()
    # 分析集合：当前版本的两篇（旧版本那篇版本不符）
    assert analysis_only["total"] == 2
    assert analysis_only["stats_mode"] is None

    system_only = client.get(
        "/api/papers",
        params={"keyword": "目标检测", "keyword_origin": "system", "page_size": 50},
    ).json()
    assert system_only["total"] == 0

    author_only = client.get(
        "/api/papers",
        params={"keyword": "目标检测", "keyword_origin": "author", "page_size": 50},
    ).json()
    assert author_only["total"] == 1


def test_invalid_keyword_origin_is_rejected(client):
    response = client.get("/api/papers", params={"keyword_origin": "unknown"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_parameter"


def test_fuzzy_query_respects_stats_origin(client, temp_db: Path):
    """模糊查询里的关键词命中同样受来源约束，否则统计口径仍会被绕过。"""
    _dataset(temp_db)

    plain = client.get(
        "/api/papers", params={"q": "目标检测", "page_size": 50}
    ).json()
    assert plain["total"] == 1

    scoped = client.get(
        "/api/papers",
        params={"q": "目标检测", "keyword_origin": "system", "page_size": 50},
    ).json()
    assert scoped["total"] == 0
