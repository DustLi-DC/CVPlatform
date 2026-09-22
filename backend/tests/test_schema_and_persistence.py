"""结构一致性、持久化与迁移的验证。

- test_schema_matches_models：迁移 DDL 与 SQLModel 模型的一致性。
  表结构由迁移的显式 DDL 创建（而不是 create_all），模型只用于查询，
  因此必须有测试守住“两边不漂移”。
- test_persistence_across_reopen：重启保留数据（关掉引擎重开）。
- test_upgrade_from_old_version_backs_up_first：升级前留一份可用备份。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlmodel import SQLModel, text

from app.config import CONFERENCES, environment, resolve_database_path
from app.db.migrations import (
    LATEST_VERSION,
    MIGRATIONS,
    initialize_database,
    read_user_version,
)
from app.models.entities import Paper

from .helpers import add_system_keyword, connect, insert_paper, insert_topic

EXPECTED_VIEWS = ("v_corpus_paper", "v_analysis_paper", "v_analysis_keyword")


def test_schema_matches_models(temp_db: Path):
    """每一张模型的表、每一个列都必须在数据库里真实存在。"""
    with connect(temp_db) as connection:
        actual_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        model_tables = set(SQLModel.metadata.tables.keys())
        assert not (model_tables - actual_tables), (
            f"模型定义了但数据库缺少的表：{model_tables - actual_tables}"
        )

        drift: list[str] = []
        for table_name, table in SQLModel.metadata.tables.items():
            if table_name not in actual_tables:
                continue
            actual_columns = {
                row[1]
                for row in connection.execute(f"PRAGMA table_info({table_name})")
            }
            missing = {column.name for column in table.columns} - actual_columns
            if missing:
                drift.append(f"{table_name} 缺少列 {missing}")
        assert not drift, "；".join(drift) + "（模型与迁移 DDL 已漂移，需要补一条迁移）"


def test_schema_has_expected_views(temp_db: Path):
    with connect(temp_db) as connection:
        views = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'view'"
            ).fetchall()
        }
    for view in EXPECTED_VIEWS:
        assert view in views


def test_analysis_views_respect_keyword_status(temp_db: Path):
    """分析集合要求已完成当前版本的关键词处理；语料集合只要求标题可用。"""
    done = insert_paper(
        temp_db,
        code="CVPR-2024-0001",
        title="Title Done",
        keyword_status="done",
        keyword_ruleset_version="kw-v1",
    )
    pending = insert_paper(temp_db, code="CVPR-2024-0002", title="Title Pending")
    stale = insert_paper(
        temp_db,
        code="CVPR-2024-0003",
        title="Title Stale",
        keyword_status="done",
        keyword_ruleset_version="kw-v0",
    )

    with connect(temp_db) as connection:
        analysis_ids = {
            row[0] for row in connection.execute("SELECT id FROM v_analysis_paper")
        }
        corpus_ids = {
            row[0] for row in connection.execute("SELECT id FROM v_corpus_paper")
        }

    # 只有“已完成且版本为当前版本”的论文进入分析集合
    assert analysis_ids == {done}
    # 语料集合不要求关键词处理完成，因此三篇都在（关键词处理可直接消费它）
    assert corpus_ids == {done, pending, stale}


def test_analysis_keyword_view_filters_origin_and_version(temp_db: Path):
    paper_id = insert_paper(
        temp_db,
        title="Title One Long",
        keyword_status="done",
        keyword_ruleset_version="kw-v1",
    )
    add_system_keyword(
        temp_db, paper_id=paper_id, name="system current", version="kw-v1"
    )
    add_system_keyword(
        temp_db,
        paper_id=paper_id,
        name="author current",
        version="kw-v1",
    )
    add_system_keyword(
        temp_db, paper_id=paper_id, name="system old", version="kw-v0"
    )

    with connect(temp_db) as connection:
        # 作者关键词行需要把 origin 改成 author，才能覆盖“来源过滤”
        connection.execute(
            "UPDATE keyword SET origin = 'author' WHERE name = 'author current'"
        )
        names = [
            row[0]
            for row in connection.execute(
                "SELECT k.name FROM v_analysis_keyword ak"
                " JOIN keyword k ON k.id = ak.keyword_id"
            ).fetchall()
        ]

    # 只保留“系统关键词 + 当前版本”，作者关键词与旧版本都不进入统计口径
    assert names == ["system current"]


def test_deleting_paper_cascades_at_database_level(temp_db: Path):
    paper_id = insert_paper(temp_db, title="Title One Long")
    with connect(temp_db) as connection:
        connection.execute(
            "INSERT INTO paper_source (paper_id, source, source_id, retrieved_at)"
            " VALUES (?, 'cvf', 'abc', '2026-01-01T00:00:00Z')",
            (paper_id,),
        )
        connection.execute(
            "INSERT INTO collection_task (kind, total_count, status, created_at)"
            " VALUES ('batch', 1, 'success', '2026-01-01T00:00:00Z')"
        )
        task_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        connection.execute(
            "INSERT INTO collection_task_item (task_id, line_no, input_title, status,"
            " paper_id, created_at, updated_at)"
            " VALUES (?, 1, 'Title One Long', 'success', ?,"
            " '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
            (task_id, paper_id),
        )
        connection.execute("DELETE FROM paper WHERE id = ?", (paper_id,))

    with connect(temp_db) as connection:
        sources = connection.execute("SELECT COUNT(*) FROM paper_source").fetchone()
        assert sources[0] == 0
        item = connection.execute(
            "SELECT paper_id, status FROM collection_task_item WHERE task_id = ?",
            (task_id,),
        ).fetchone()
    # 任务明细保留历史，但引用置空
    assert item[0] is None
    assert item[1] == "success"


def test_persistence_across_reopen(client, paper_factory, temp_db: Path):
    """写入后重新建立引擎与连接，数据仍在——验证重启保留数据。"""
    created = paper_factory(
        "A Title That Must Survive A Restart", conference="CVPR", year=2024
    )

    from fastapi.testclient import TestClient

    from app.db.engine import reset_engine
    from app.main import app

    reset_engine()
    with TestClient(app) as reopened:
        detail = reopened.get(f"/api/papers/{created['id']}")
        assert detail.status_code == 200
        assert detail.json()["title"] == "A Title That Must Survive A Restart"
        assert reopened.get("/api/papers").json()["total"] == 1


def test_initialize_is_idempotent_and_keeps_data(temp_db: Path):
    insert_paper(temp_db, title="Title One Long")

    # 再次初始化：不执行迁移、不新建备份、不动数据
    summary = initialize_database(temp_db)
    assert summary["applied"] == []
    assert summary["backup_path"] is None

    with connect(temp_db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM paper").fetchone()[0] == 1
        assert read_user_version(connection) == LATEST_VERSION


def test_upgrade_from_old_version_backs_up_first(temp_db: Path):
    """模拟旧版本数据库升级：先降到 v0，再初始化，应当留一份可用备份且数据保留。"""
    insert_paper(temp_db, title="Title Survives Upgrade")
    with connect(temp_db) as connection:
        connection.execute("DROP VIEW v_analysis_keyword")
        connection.execute("PRAGMA user_version = 0")

    summary = initialize_database(temp_db)
    assert summary["applied"] == [item.version for item in MIGRATIONS]
    assert summary["backup_path"] is not None
    backup = Path(str(summary["backup_path"]))
    assert backup.exists() and backup.stat().st_size > 0

    # 备份必须是完整可读的数据库，而不是写了一半的文件
    with connect(backup) as backup_connection:
        tables = backup_connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
        ).fetchone()[0]
    assert tables > 0

    with connect(temp_db) as connection:
        assert read_user_version(connection) == LATEST_VERSION
        assert connection.execute("SELECT COUNT(*) FROM paper").fetchone()[0] == 1


def test_foreign_keys_are_enabled_on_app_connections(temp_db: Path):
    """应用连接必须开启外键，否则级联删除不会生效。"""
    from sqlmodel import Session

    from app.db.engine import get_engine

    with Session(get_engine()) as session:
        assert session.exec(text("PRAGMA foreign_keys")).one()[0] == 1
        assert session.exec(text("PRAGMA journal_mode")).one()[0].lower() == "wal"


def test_conference_list_is_shared_single_source():
    assert CONFERENCES == ("CVPR", "ICCV", "ECCV")
    assert LATEST_VERSION >= 1


def test_database_path_configuration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from app.config import reset_path_cache

    # 1) 显式路径优先
    explicit = tmp_path / "explicit.db"
    monkeypatch.setenv("CVPLATFORM_DB_PATH", str(explicit))
    assert resolve_database_path() == explicit.resolve()

    # 2) 生产环境默认路径
    monkeypatch.delenv("CVPLATFORM_DB_PATH", raising=False)
    monkeypatch.setenv("CVPLATFORM_ENV", "production")
    assert resolve_database_path() == Path("/var/lib/cvplatform/cvplatform.db")
    assert environment() == "production"

    # 3) 测试环境落在系统临时目录
    monkeypatch.setenv("CVPLATFORM_ENV", "test")
    reset_path_cache()
    assert resolve_database_path().name.startswith("cvplatform-test-")

    # 4) 开发默认锚定仓库根，与当前工作目录无关
    monkeypatch.delenv("CVPLATFORM_ENV", raising=False)
    dev_path = resolve_database_path()
    assert dev_path.parent.name == "data"
    assert (dev_path.parent.parent / "README.md").exists()
    assert dev_path.is_absolute()
