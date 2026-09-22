"""主题归并层与数据维护的测试。

覆盖：主题表的读取与归一、映射与「未归类」的如实保留、
摘要 HTML 实体的定点修复（默认试运行、显式写入才改数据）、
以及分析集合版本在各类写入后是否自增（决定统计缓存是否失效）。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.config import KEYWORD_RULESET_VERSION
from app.db.engine import session_scope
from app.services import maintenance, topic_layer
from tests.helpers import connect, insert_paper


def test_load_topic_file_normalizes_aliases(tmp_path: Path):
    """主题文件读取：别名做词形归一，主题名本身也作为别名。"""
    path = tmp_path / "topics.json"
    path.write_text(
        json.dumps(
            {
                "版本": "topic-test",
                "主题": [
                    {
                        "slug": "demo",
                        "name": "示例主题",
                        "group_name": "perception",
                        "aliases": ["Object Detection", "detections"],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    version, entries = topic_layer.load_topic_file(path)
    assert version == "topic-test"
    assert entries[0].slug == "demo"
    assert "object detection" in entries[0].aliases
    assert "detection" in entries[0].aliases
    assert "示例主题" in entries[0].aliases


def test_load_topic_file_rejects_broken_input(tmp_path: Path):
    """主题表缺版本或不是合法 JSON 时必须报错，不能静默按关键词统计。"""
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        topic_layer.load_topic_file(broken)

    missing = tmp_path / "missing.json"
    missing.write_text(json.dumps({"主题": []}, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError):
        topic_layer.load_topic_file(missing)


def test_real_topic_file_is_usable():
    """仓库内的主题表必须可解析，且规模与依据样本相符。"""
    version, entries = topic_layer.load_topic_file()
    assert version.startswith("topic-v")
    assert 30 <= len(entries) <= 60
    slugs = [entry.slug for entry in entries]
    assert len(slugs) == len(set(slugs)), "slug 不能重复"
    aliases: list[str] = []
    for entry in entries:
        assert entry.aliases, f"{entry.slug} 至少要有一个别名"
        aliases.extend(entry.aliases)
    assert len(aliases) == len(set(aliases)), "同一别名不能属于多个主题"


def test_sync_topics_maps_keywords_and_keeps_unmapped(temp_db: Path):
    """映射只覆盖能匹配别名的关键词，匹配不到的保持未归类。"""
    paper_id = insert_paper(
        temp_db,
        code="CVPR-2024-0001",
        title="Topic Sync Paper For Tests",
        keyword_status="done",
        keyword_ruleset_version=KEYWORD_RULESET_VERSION,
    )
    from tests.helpers import add_system_keyword

    add_system_keyword(temp_db, paper_id=paper_id, name="object detection")
    add_system_keyword(temp_db, paper_id=paper_id, name="totally unmapped term")

    with session_scope() as session:
        result = topic_layer.sync_topics(session)
    assert result["mapped_keywords"] == 1

    with connect(temp_db) as connection:
        rows = dict(
            connection.execute(
                "SELECT name, topic_id IS NOT NULL FROM keyword WHERE origin='system'"
            ).fetchall()
        )
    assert rows["object detection"] == 1
    assert rows["totally unmapped term"] == 0


def test_sync_topics_deactivates_removed_topics(temp_db: Path, tmp_path: Path):
    """文件里删掉的主题置为停用而不是物理删除，历史口径可回溯。"""
    first = tmp_path / "first.json"
    first.write_text(
        json.dumps(
            {
                "版本": "topic-a",
                "主题": [
                    {"slug": "keep", "name": "保留主题", "aliases": ["keep keyword"]},
                    {"slug": "drop", "name": "被删主题", "aliases": ["drop keyword"]},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    second = tmp_path / "second.json"
    second.write_text(
        json.dumps(
            {
                "版本": "topic-b",
                "主题": [{"slug": "keep", "name": "保留主题", "aliases": ["keep keyword"]}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with session_scope() as session:
        topic_layer.sync_topics(session, path=first)
    with session_scope() as session:
        result = topic_layer.sync_topics(session, path=second)
    assert result["deactivated"] == 1

    with connect(temp_db) as connection:
        states = dict(connection.execute("SELECT slug, is_active FROM topic").fetchall())
    assert states == {"keep": 1, "drop": 0}


def test_repair_html_entities_is_dry_run_by_default(temp_db: Path):
    """默认只统计不写入；摘要里的 &#x27; 必须如实报告数量与替换种类。"""
    paper_id = insert_paper(
        temp_db,
        code="CVPR-2024-0001",
        title="Entity Repair Paper For Tests",
        keyword_status="done",
        keyword_ruleset_version=KEYWORD_RULESET_VERSION,
    )
    with connect(temp_db) as connection:
        connection.execute(
            "UPDATE paper SET abstract = ? WHERE id = ?",
            ("We improve the model&#x27;s accuracy and use &quot;masks&quot;.", paper_id),
        )

    with session_scope() as session:
        preview = maintenance.repair_html_entities(session, apply=False)
    assert preview["changed"] == 1
    assert preview["applied"] is False
    assert "&#x27; → '" in preview["entity_kinds"]

    with connect(temp_db) as connection:
        stored = connection.execute(
            "SELECT abstract FROM paper WHERE id = ?", (paper_id,)
        ).fetchone()[0]
    assert "&#x27;" in stored, "试运行不得修改数据"

    with session_scope() as session:
        applied = maintenance.repair_html_entities(session, apply=True)
    assert applied["changed"] == 1
    with connect(temp_db) as connection:
        stored = connection.execute(
            "SELECT abstract FROM paper WHERE id = ?", (paper_id,)
        ).fetchone()[0]
    assert stored == 'We improve the model\'s accuracy and use "masks".'
    # 修复结果可重复：再跑一次没有需要改的
    with session_scope() as session:
        again = maintenance.repair_html_entities(session, apply=True)
    assert again["changed"] == 0


def test_analysis_version_increments_on_writes(temp_db: Path):
    """写入路径必须自增分析集合版本，否则统计缓存不会失效。"""
    with session_scope() as session:
        start = maintenance.read_analysis_version(session)

    paper_id = insert_paper(
        temp_db,
        code="CVPR-2024-0001",
        title="Version Counter Paper For Tests",
        keyword_status="done",
        keyword_ruleset_version=KEYWORD_RULESET_VERSION,
    )
    with session_scope() as session:
        after_insert = maintenance.mark_analysis_changed(session)
    assert after_insert > start

    from tests.helpers import add_system_keyword

    add_system_keyword(temp_db, paper_id=paper_id, name="object detection")
    with session_scope() as session:
        after_link = maintenance.mark_analysis_changed(session)
    assert after_link > after_insert


def test_keyword_write_paths_bump_analysis_version(temp_db: Path):
    """关键词写入与清除也会让分析集合版本变化（统计据此判断缓存失效）。"""
    paper_id = insert_paper(
        temp_db,
        code="CVPR-2024-0001",
        title="Keyword Write Paper For Tests",
        keyword_status="pending",
    )
    from app.services.keywords import clear_system_keywords, sync_paper_keywords
    from sqlmodel import Session

    from app.db.engine import get_engine

    assert paper_id
    with Session(get_engine()) as session:
        before = maintenance.read_analysis_version(session)

    with Session(get_engine()) as session:
        paper = session.get(__import__("app.models.entities", fromlist=["Paper"]).Paper, paper_id)
        sync_paper_keywords(session, paper, author_keywords=["author kw"], system_keywords=["system kw"])
        session.commit()
    with Session(get_engine()) as session:
        after_sync = maintenance.read_analysis_version(session)
    assert after_sync > before

    with Session(get_engine()) as session:
        clear_system_keywords(session, paper_id)
        session.commit()
    with Session(get_engine()) as session:
        after_clear = maintenance.read_analysis_version(session)
    assert after_clear > after_sync


def test_status_counts_reports_pending_and_mapping(temp_db: Path):
    """状态汇总：待处理量、各状态分布与主题映射数量。"""
    paper_id = insert_paper(
        temp_db,
        code="CVPR-2024-0001",
        title="Status Counts Paper For Tests",
        keyword_status="done",
        keyword_ruleset_version="kw-v2",  # 旧版本 → 记为待重算
    )
    insert_paper(
        temp_db,
        code="CVPR-2024-0002",
        title="Another Status Paper For Tests",
        keyword_status="pending",
    )
    from app.services import keyword_job

    with session_scope() as session:
        counts = keyword_job.status_counts(session)
    assert counts["corpus_papers"] == 2
    assert counts["analysis_papers"] == 0
    assert counts["by_status"] == {"done": 1, "pending": 1}
    assert counts["pending_or_stale"] == 2
    assert counts["ruleset_version"] == KEYWORD_RULESET_VERSION
    assert counts["system_keywords"] == 0
    assert paper_id


def test_repair_does_not_touch_text_without_entities(temp_db: Path):
    """没有实体的摘要不应被改动（避免顺手改写真实正文）。"""
    paper_id = insert_paper(
        temp_db,
        code="CVPR-2024-0001",
        title="Plain Abstract Paper For Tests",
        keyword_status="done",
        keyword_ruleset_version=KEYWORD_RULESET_VERSION,
    )
    plain = "A normal abstract with an ampersand & and less-than < signs."
    with connect(temp_db) as connection:
        connection.execute("UPDATE paper SET abstract = ? WHERE id = ?", (plain, paper_id))

    with session_scope() as session:
        result = maintenance.repair_html_entities(session, apply=True)
    assert result["changed"] == 0
    with connect(temp_db) as connection:
        stored = connection.execute(
            "SELECT abstract FROM paper WHERE id = ?", (paper_id,)
        ).fetchone()[0]
    assert stored == plain
