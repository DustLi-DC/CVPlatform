"""测试用的数据库操作助手。

部分用例需要绕过服务层直接构造数据库状态（例如模拟阶段 5 才会写入的系统关键词、
旧规则版本的历史行、或主题归并结果），集中放在这里以便复用并缩短各用例。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.config import KEYWORD_RULESET_VERSION

# 固定时间戳：让构造出来的行具有确定的时间字段，便于排查
NOW = "2026-01-01T00:00:00Z"


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    """打开连接并开启外键（否则级联删除不生效），正常退出时提交。"""
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def insert_paper(
    db_path: Path,
    *,
    code: str = "CVPR-2024-0001",
    conference: str = "CVPR",
    year: int = 2024,
    title: str = "A Default Paper Title For Tests",
    abstract_status: str = "present",
    data_status: str = "complete",
    keyword_status: str = "pending",
    keyword_ruleset_version: str | None = None,
) -> int:
    """直接插入一条论文记录，返回其 id。"""
    title_normalized = title.lower()
    dedup_key = f"{conference}|{year}|{title_normalized}"
    with connect(db_path) as connection:
        connection.execute(
            "INSERT INTO paper (code, code_origin_conference, code_origin_year,"
            " dedup_key, title, title_normalized, conference, year, abstract_status,"
            " primary_source, data_status, keyword_status, keyword_ruleset_version,"
            " created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'manual', ?, ?, ?, ?, ?)",
            (
                code,
                conference,
                year,
                dedup_key,
                title,
                title_normalized,
                conference,
                year,
                abstract_status,
                data_status,
                keyword_status,
                keyword_ruleset_version,
                NOW,
                NOW,
            ),
        )
        return int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])


def upsert_keyword(
    db_path: Path,
    *,
    name: str,
    origin: str = "system",
    topic_id: int | None = None,
    doc_freq: int = 1,
) -> int:
    """取回或创建关键词行（唯一键为 归一形式 + 来源），返回其 id。"""
    normalized = name.lower()
    with connect(db_path) as connection:
        connection.execute(
            "INSERT INTO keyword (name, name_normalized, language, origin, topic_id,"
            " doc_freq, created_at) VALUES (?, ?, 'en', ?, ?, ?, ?)"
            " ON CONFLICT (name_normalized, origin) DO NOTHING",
            (name, normalized, origin, topic_id, doc_freq, NOW),
        )
        row = connection.execute(
            "SELECT id FROM keyword WHERE name_normalized = ? AND origin = ?",
            (normalized, origin),
        ).fetchone()
        assert row is not None
        return int(row[0])


def link_keyword(
    db_path: Path,
    *,
    paper_id: int,
    keyword_id: int,
    version: str = KEYWORD_RULESET_VERSION,
) -> None:
    """建立论文与关键词的关系。"""
    with connect(db_path) as connection:
        connection.execute(
            "INSERT INTO paper_keyword (paper_id, keyword_id, ruleset_version,"
            " created_at) VALUES (?, ?, ?, ?)",
            (paper_id, keyword_id, version, NOW),
        )


def add_system_keyword(
    db_path: Path,
    *,
    paper_id: int,
    name: str,
    version: str = KEYWORD_RULESET_VERSION,
    topic_id: int | None = None,
) -> int:
    """插入系统关键词并关联到论文，返回关键词 id。"""
    keyword_id = upsert_keyword(
        db_path, name=name, origin="system", topic_id=topic_id
    )
    link_keyword(db_path, paper_id=paper_id, keyword_id=keyword_id, version=version)
    return keyword_id


def insert_topic(
    db_path: Path,
    *,
    slug: str,
    name: str,
    group_name: str = "perception",
    sort_order: int = 0,
) -> int:
    """插入主题，返回其 id。"""
    with connect(db_path) as connection:
        connection.execute(
            "INSERT INTO topic (slug, name, group_name, is_active, sort_order,"
            " created_at) VALUES (?, ?, ?, 1, ?, ?)",
            (slug, name, group_name, sort_order, NOW),
        )
        return int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])


def set_meta(db_path: Path, key: str, value: str) -> None:
    """写入或覆盖 meta 键值。"""
    with connect(db_path) as connection:
        connection.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?)"
            " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def count_rows(
    db_path: Path,
    table: str,
    where: str = "1 = 1",
    params: tuple[Any, ...] = (),
) -> int:
    """统计行数。table/where 由调用方以字面量传入，不涉及用户输入。"""
    with connect(db_path) as connection:
        row = connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {where}", params
        ).fetchone()
        return int(row[0]) if row else 0


def read_user_version(db_path: Path) -> int:
    with connect(db_path) as connection:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])
