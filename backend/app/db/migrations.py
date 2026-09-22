"""数据库结构与版本迁移。

设计依据：开发设计与验收.md 第 3.5 节。

约定：
- 版本载体为 SQLite 的 PRAGMA user_version，配合 meta.schema_note 记录可读版本名。
- 迁移按 version 升序执行，每步只执行一次；语句本身写成幂等（IF NOT EXISTS /
  先查 PRAGMA table_info 再 ADD COLUMN），避免重复执行出错。
- 只增列不删列、不改列类型；需要改语义时新增列并回填。
- 升级前用 SQLite 在线备份接口留档：数据库启用 WAL 后，已提交数据可能仍在 -wal
  文件中，直接复制主文件会得到不完整备份，因此不按文件大小分情况处理，
  统一使用 Connection.backup()。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..config import KEYWORD_RULESET_VERSION, TOPIC_RULESET_VERSION


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]


# 初始结构。表列与 models/entities.py 一一对应，由 tests/test_schema.py 校验一致性。
_V1_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS paper (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL UNIQUE,
        code_origin_conference TEXT NOT NULL,
        code_origin_year INTEGER NOT NULL,
        dedup_key TEXT NOT NULL UNIQUE,
        title TEXT NOT NULL,
        title_normalized TEXT NOT NULL,
        conference TEXT NOT NULL,
        year INTEGER NOT NULL,
        abstract TEXT,
        abstract_status TEXT NOT NULL DEFAULT 'missing',
        authors_json TEXT,
        keywords_source_json TEXT,
        landing_url TEXT,
        pdf_url TEXT,
        primary_source TEXT NOT NULL DEFAULT 'manual',
        data_status TEXT NOT NULL DEFAULT 'review',
        keyword_status TEXT NOT NULL DEFAULT 'pending',
        keyword_ruleset_version TEXT,
        keyword_processed_at TEXT,
        retrieved_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        CHECK (conference IN ('CVPR', 'ICCV', 'ECCV')),
        CHECK (year > 0),
        CHECK (abstract_status IN ('present', 'missing')),
        CHECK (data_status IN ('complete', 'review', 'failed')),
        CHECK (keyword_status IN ('pending', 'running', 'done', 'failed'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_paper_title_normalized ON paper (title_normalized)",
    "CREATE INDEX IF NOT EXISTS idx_paper_conference_year ON paper (conference, year)",
    "CREATE INDEX IF NOT EXISTS idx_paper_keyword_status ON paper (keyword_status)",
    "CREATE INDEX IF NOT EXISTS idx_paper_data_status ON paper (data_status)",
    """
    CREATE TABLE IF NOT EXISTS topic (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slug TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        group_name TEXT,
        is_active INTEGER NOT NULL DEFAULT 1,
        sort_order INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS topic_alias (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_id INTEGER NOT NULL REFERENCES topic (id) ON DELETE CASCADE,
        alias_normalized TEXT NOT NULL UNIQUE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_topic_alias_topic ON topic_alias (topic_id)",
    """
    CREATE TABLE IF NOT EXISTS keyword (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        name_normalized TEXT NOT NULL,
        language TEXT NOT NULL DEFAULT 'en',
        origin TEXT NOT NULL,
        topic_id INTEGER REFERENCES topic (id) ON DELETE SET NULL,
        doc_freq INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        CHECK (origin IN ('author', 'system')),
        CHECK (language IN ('en', 'zh')),
        UNIQUE (name_normalized, origin)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_keyword_name_normalized"
    " ON keyword (name_normalized)",
    "CREATE INDEX IF NOT EXISTS idx_keyword_origin ON keyword (origin)",
    """
    CREATE TABLE IF NOT EXISTS paper_keyword (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        paper_id INTEGER NOT NULL REFERENCES paper (id) ON DELETE CASCADE,
        keyword_id INTEGER NOT NULL REFERENCES keyword (id) ON DELETE CASCADE,
        tfidf_score REAL,
        textrank_score REAL,
        rank INTEGER,
        ruleset_version TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (paper_id, keyword_id, ruleset_version)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_paper_keyword_paper ON paper_keyword (paper_id)",
    "CREATE INDEX IF NOT EXISTS idx_paper_keyword_keyword"
    " ON paper_keyword (keyword_id)",
    "CREATE INDEX IF NOT EXISTS idx_paper_keyword_version"
    " ON paper_keyword (ruleset_version)",
    """
    CREATE TABLE IF NOT EXISTS paper_source (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        paper_id INTEGER NOT NULL REFERENCES paper (id) ON DELETE CASCADE,
        source TEXT NOT NULL,
        source_id TEXT NOT NULL,
        url TEXT,
        retrieved_at TEXT,
        UNIQUE (source, source_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_paper_source_paper ON paper_source (paper_id)",
    """
    CREATE TABLE IF NOT EXISTS collection_task (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL DEFAULT 'batch',
        file_name TEXT,
        file_size INTEGER,
        file_format TEXT,
        sample_stride INTEGER,
        sample_limit INTEGER,
        total_count INTEGER NOT NULL DEFAULT 0,
        pending_count INTEGER NOT NULL DEFAULT 0,
        running_count INTEGER NOT NULL DEFAULT 0,
        success_count INTEGER NOT NULL DEFAULT 0,
        duplicate_count INTEGER NOT NULL DEFAULT 0,
        failed_count INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'pending',
        message TEXT,
        ruleset_version TEXT,
        created_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT,
        CHECK (status IN ('pending','running','interrupted','partial',
                          'success','failed','canceled'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_collection_task_status ON collection_task (status)",
    """
    CREATE TABLE IF NOT EXISTS collection_task_item (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL REFERENCES collection_task (id) ON DELETE CASCADE,
        line_no INTEGER NOT NULL,
        input_title TEXT NOT NULL,
        input_conference TEXT,
        input_year INTEGER,
        status TEXT NOT NULL DEFAULT 'pending',
        paper_id INTEGER REFERENCES paper (id) ON DELETE SET NULL,
        duplicate_of_paper_id INTEGER REFERENCES paper (id) ON DELETE SET NULL,
        message TEXT,
        attempts INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        CHECK (status IN ('pending','running','success','duplicate','failed'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_task_item_task ON collection_task_item (task_id)",
    "CREATE INDEX IF NOT EXISTS idx_task_item_status ON collection_task_item (status)",
    """
    CREATE TABLE IF NOT EXISTS conference_year_seq (
        conference TEXT NOT NULL,
        year INTEGER NOT NULL,
        next_seq INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (conference, year)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS idf_term (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        term_normalized TEXT NOT NULL,
        df INTEGER NOT NULL,
        idf REAL NOT NULL,
        ruleset_version TEXT NOT NULL,
        corpus_size INTEGER NOT NULL,
        UNIQUE (term_normalized, ruleset_version)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_idf_term_version ON idf_term (ruleset_version)",
    """
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    # 语料集合：只要求真实、会议年份有效、标题可用，不要求已完成关键词处理，
    # 因此关键词处理本身可以直接消费它，不存在循环依赖。
    """
    CREATE VIEW IF NOT EXISTS v_corpus_paper AS
    SELECT p.id AS id, p.title AS title, p.abstract AS abstract,
           p.conference AS conference, p.year AS year
    FROM paper p
    WHERE p.conference IN ('CVPR', 'ICCV', 'ECCV')
      AND p.year > 0
      AND length(p.title_normalized) >= 4
    """,
    # 分析集合：统计口径的唯一来源（分母）。
    """
    CREATE VIEW IF NOT EXISTS v_analysis_paper AS
    SELECT p.id AS id, p.conference AS conference, p.year AS year,
           p.title AS title, p.title_normalized AS title_normalized
    FROM paper p
    WHERE p.conference IN ('CVPR', 'ICCV', 'ECCV')
      AND p.year > 0
      AND length(p.title_normalized) >= 4
      AND p.keyword_status = 'done'
      AND p.keyword_ruleset_version = (
          SELECT value FROM meta WHERE key = 'keyword_ruleset_version'
      )
    """,
    # 分析集合中的系统关键词：统计类查询的唯一入口，避免调用方漏写版本与来源条件。
    """
    CREATE VIEW IF NOT EXISTS v_analysis_keyword AS
    SELECT pk.paper_id AS paper_id, pk.keyword_id AS keyword_id
    FROM paper_keyword pk
    JOIN v_analysis_paper ap ON ap.id = pk.paper_id
    JOIN keyword k ON k.id = pk.keyword_id
    WHERE k.origin = 'system'
      AND pk.ruleset_version = (
          SELECT value FROM meta WHERE key = 'keyword_ruleset_version'
      )
    """,
)

MIGRATIONS: tuple[Migration, ...] = (
    Migration(version=1, name="initial_schema", statements=_V1_STATEMENTS),
)

LATEST_VERSION = max(item.version for item in MIGRATIONS)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_user_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row else 0


def backup_database(db_path: Path, *, reason: str = "manual") -> Path | None:
    """用 SQLite 在线备份接口生成一致快照。

    数据库启用 WAL 时，直接复制主文件可能丢失仍在 -wal 中的已提交数据，
    因此始终通过 Connection.backup() 读取，不做“按文件大小决定复制方式”的分支。
    """
    if not db_path.exists():
        return None
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = db_path.with_name(f"{db_path.name}.bak-{reason}-{stamp}")
    source = sqlite3.connect(db_path)
    try:
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()
    return target


def _apply_migration(conn: sqlite3.Connection, migration: Migration) -> None:
    for statement in migration.statements:
        conn.execute(statement)
    conn.execute(f"PRAGMA user_version = {migration.version}")
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('schema_note', ?) "
        "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        (f"{migration.version:04d}_{migration.name}",),
    )


def initialize_database(
    db_path: Path, *, make_backup: bool = True
) -> dict[str, object]:
    """创建或升级数据库到最新版本，返回本次执行摘要。

    可重复运行：已是最新版本时不执行任何迁移；从旧版本升级时逐级执行。
    升级前会先做一次在线备份（仅当数据库已存在且需要变更结构时）。
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    existed_before = db_path.exists()

    # 连接前先确认目录可写，避免在只读目录上产生模糊错误
    if not existed_before:
        probe = db_path.parent / ".cvplatform-write-probe"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as error:  # pragma: no cover - 权限问题由部署环境决定
            raise PermissionError(
                f"数据库目录不可写：{db_path.parent}。请确认运行用户对该目录有写权限。"
            ) from error

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        # meta 表可能还不存在，先建最小结构以便迁移记录版本名
        conn.execute(
            "CREATE TABLE IF NOT EXISTS meta ("
            "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )

        current = read_user_version(conn)
        pending = [item for item in MIGRATIONS if item.version > current]
        backup_path: Path | None = None

        if pending and existed_before and make_backup:
            backup_path = backup_database(db_path, reason=f"v{current}")

        for migration in pending:
            _apply_migration(conn, migration)

        # 规则版本以代码为唯一来源：每次初始化都同步到 meta，
        # 否则提升版本后视图仍按旧版本过滤，刚处理完的论文反而进不了分析集合。
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('keyword_ruleset_version', ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (KEYWORD_RULESET_VERSION,),
        )
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('topic_ruleset_version', ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (TOPIC_RULESET_VERSION,),
        )
        conn.commit()

        return {
            "database_path": str(db_path),
            "from_version": current,
            "to_version": read_user_version(conn),
            "applied": [item.version for item in pending],
            "backup_path": str(backup_path) if backup_path else None,
            "created": not existed_before,
        }
    finally:
        conn.close()
