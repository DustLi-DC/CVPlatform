"""阶段 3 复核问题的回归用例。

每一项对应人工复核指出的一个缺陷，修复后必须长期有效：
1. 备份脚本默认目录与清理范围（避免误删无关数据库）
2. 并发新增的编号分配竞争
3. 作者关键词可真正清空
4. 测试环境默认库路径在同一进程中固定
5. 含连字符的标题模糊查询
6. 关键词读取按当前版本过滤、不出现重复或淘汰词
7. 状态筛选的枚举校验
8. 迁移模块不再提供“注释说在线备份、实际复制文件”的函数
"""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

from .helpers import (
    add_system_keyword,
    count_rows,
    insert_paper,
    set_meta,
)

BACKUP_SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "backup_database.py"


def _make_db_with_row(db_path: Path) -> None:
    """建一个带已提交数据的库；数据可能只存在于 -wal 中，正是备份容易出错的场景。"""
    from app.db.migrations import initialize_database

    initialize_database(db_path)
    set_meta(db_path, "probe_key", "probe_value")


# ---------------------------------------------------------------- 1. 备份脚本


def test_backup_script_omitting_dir_does_not_write_to_cwd(tmp_path: Path, monkeypatch):
    """省略备份目录时，备份必须落在数据库同级的 backups/，而不是当前工作目录。"""
    db_path = tmp_path / "data" / "cvplatform.db"
    db_path.parent.mkdir(parents=True)
    _make_db_with_row(db_path)

    working_dir = tmp_path / "cwd"
    working_dir.mkdir()
    monkeypatch.delenv("CVPLATFORM_BACKUP_DIR", raising=False)

    result = subprocess.run(
        [sys.executable, str(BACKUP_SCRIPT), str(db_path)],
        capture_output=True,
        text=True,
        cwd=working_dir,
    )
    assert result.returncode == 0, result.stderr

    expected_dir = db_path.parent / "backups"
    assert expected_dir.is_dir()
    assert list(expected_dir.glob("*.db")), "备份未落在数据库同级的 backups 目录"
    # 当前工作目录必须保持干净
    assert list(working_dir.glob("*.db")) == []


def test_backup_script_never_deletes_unrelated_databases(tmp_path: Path):
    """清理逻辑只能删本脚本为同一数据库生成的备份，不能碰到其他 .db 文件。"""
    db_path = tmp_path / "cvplatform.db"
    _make_db_with_row(db_path)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    unrelated = backup_dir / "another-project.db"
    unrelated.write_text("this must survive", encoding="utf-8")
    notes = backup_dir / "notes.txt"
    notes.write_text("keep me", encoding="utf-8")

    for _ in range(3):
        result = subprocess.run(
            [sys.executable, str(BACKUP_SCRIPT), str(db_path), str(backup_dir)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    assert unrelated.read_text(encoding="utf-8") == "this must survive"
    assert notes.exists()
    backups = sorted(backup_dir.glob("cvplatform-*.db"))
    assert backups, "本数据库的备份没有生成"
    # 备份文件名符合模式，且无关文件不在其中
    assert all(item.name.endswith("Z.db") for item in backups)
    assert unrelated not in backups


def test_backup_script_backup_contains_committed_data(tmp_path: Path):
    """备份内容必须包含已提交数据（这正是直接复制主文件会丢数据的场景）。"""
    db_path = tmp_path / "cvplatform.db"
    _make_db_with_row(db_path)

    result = subprocess.run(
        [sys.executable, str(BACKUP_SCRIPT), str(db_path), str(tmp_path / "backups")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    backup = next((tmp_path / "backups").glob("cvplatform-*.db"))
    assert count_rows(backup, "meta", "key = 'probe_key'") == 1


def test_backup_script_respects_keep_limit(tmp_path: Path):
    """连续备份时按保留份数清理，只清理自己的历史备份。"""
    db_path = tmp_path / "cvplatform.db"
    _make_db_with_row(db_path)
    backup_dir = tmp_path / "backups"

    for _ in range(3):
        subprocess.run(
            [sys.executable, str(BACKUP_SCRIPT), str(db_path), str(backup_dir)],
            capture_output=True,
            text=True,
            check=True,
        )
    assert len(list(backup_dir.glob("cvplatform-*.db"))) >= 1


# ------------------------------------------------------------ 2. 并发编号分配


def test_concurrent_creates_get_distinct_codes(temp_db: Path):
    """并发新增不同论文时，编号必须唯一且不出现服务错误。

    直接调用服务层并在线程中并发执行：FastAPI 的同步接口在线程池中运行，
    单 worker 并不等于请求串行，这条用例覆盖的正是那个执行模型。
    """
    from sqlmodel import Session

    from app.db.engine import get_engine
    from app.services.papers import save_paper

    titles = [f"Concurrent Paper Number {index} With Long Title" for index in range(8)]
    results: list[str] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def create(title: str) -> None:
        try:
            with Session(get_engine()) as session:
                paper, _created = save_paper(
                    session, title=title, conference="CVPR", year=2024
                )
                session.commit()
                code = paper.code
            with lock:
                results.append(code)
        except BaseException as error:  # noqa: BLE001 - 记录后统一断言
            with lock:
                errors.append(error)

    threads = [threading.Thread(target=create, args=(title,)) for title in titles]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == [], f"并发新增出现异常：{errors}"
    assert len(results) == len(titles)
    # 编号互不相同，且不跳号
    assert len(set(results)) == len(titles), f"编号出现重复：{sorted(results)}"
    expected = [f"CVPR-2024-{index:04d}" for index in range(1, len(titles) + 1)]
    assert sorted(results) == expected


def test_concurrent_creates_of_same_paper_yield_conflict_not_error(temp_db: Path):
    """同一篇论文被并发提交时，最终只允许存在一条记录，且不出现非预期异常。

    服务层把“命中已有记录”视为更新（返回 created=False），严格冲突由接口层抛出；
    并发下没抢到的那几个请求会在唯一索引上失败，必须被转换成 409，
    而不是把数据库异常暴露成 500。
    """
    from sqlmodel import Session

    from app.db.engine import get_engine
    from app.services.papers import ApiError, save_paper

    title = "The Very Same Paper Submitted Twice At Once"
    outcomes: list[str] = []
    lock = threading.Lock()

    def create() -> None:
        try:
            with Session(get_engine()) as session:
                _paper, created = save_paper(
                    session, title=title, conference="CVPR", year=2024
                )
                session.commit()
            with lock:
                outcomes.append("created" if created else "existing")
        except ApiError as error:
            with lock:
                outcomes.append(f"api_error:{error.status_code}")
        except BaseException as error:  # noqa: BLE001 - 记录后统一断言
            with lock:
                outcomes.append(f"unexpected:{type(error).__name__}")

    threads = [threading.Thread(target=create) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not [item for item in outcomes if item.startswith("unexpected")], outcomes
    allowed = ("created", "existing", "api_error:409")
    assert all(item in allowed for item in outcomes), outcomes
    assert outcomes.count("created") <= 1, outcomes
    # 关键不变量：数据库里只留下一条记录
    assert count_rows(temp_db, "paper") == 1


# ------------------------------------------------------- 3. 作者关键词可清空


def test_author_keywords_can_be_cleared(client, paper_factory):
    paper = paper_factory(
        "A Paper Whose Keywords Get Removed Later",
        source_keywords=["目标检测", "语义分割"],
    )
    assert len(paper["keywords"]) == 2

    cleared = client.patch(f"/api/papers/{paper['id']}", json={"source_keywords": []})
    assert cleared.status_code == 200
    body = cleared.json()
    # 字段、标签、检索三处必须一致
    assert body["source_keywords"] == []
    assert body["keywords"] == []
    assert client.get(f"/api/papers/{paper['id']}").json()["keywords"] == []
    assert client.get("/api/papers", params={"keyword": "目标检测"}).json()["total"] == 0
    assert client.get("/api/papers", params={"q": "目标检测"}).json()["total"] == 0


def test_author_keywords_partial_removal(client, paper_factory):
    paper = paper_factory(
        "A Paper With Three Author Keywords",
        source_keywords=["目标检测", "语义分割", "三维重建"],
    )
    updated = client.patch(
        f"/api/papers/{paper['id']}", json={"source_keywords": ["三维重建"]}
    )
    assert updated.status_code == 200
    assert [item["name"] for item in updated.json()["keywords"]] == ["三维重建"]
    # 被移除的两个词不再能被检索到
    assert client.get("/api/papers", params={"keyword": "目标检测"}).json()["total"] == 0
    assert client.get("/api/papers", params={"keyword": "三维重建"}).json()["total"] == 1


def test_removed_author_keyword_can_be_added_back(client, paper_factory):
    """删除后重新加回同一个词，不能因为残留历史行而出错或出现重复标签。"""
    paper = paper_factory("A Paper With Readded Keywords", source_keywords=["目标检测"])
    client.patch(f"/api/papers/{paper['id']}", json={"source_keywords": []})
    restored = client.patch(
        f"/api/papers/{paper['id']}", json={"source_keywords": ["目标检测"]}
    )
    assert restored.status_code == 200
    names = [item["name"] for item in restored.json()["keywords"]]
    assert names == ["目标检测"]


# ------------------------------------------------- 4. 测试环境路径固定


def test_test_environment_path_is_stable_within_process(monkeypatch):
    """同一进程内多次解析必须得到同一路径，否则初始化与查询会落到不同库。"""
    from app.config import reset_path_cache, resolve_database_path

    monkeypatch.delenv("CVPLATFORM_DB_PATH", raising=False)
    monkeypatch.setenv("CVPLATFORM_ENV", "test")
    reset_path_cache()

    first = resolve_database_path()
    assert first == resolve_database_path() == resolve_database_path()
    assert first.name.startswith("cvplatform-test-")


def test_test_environment_end_to_end_without_explicit_path(monkeypatch):
    """只设 CVPLATFORM_ENV=test、不指定路径时，初始化与查询必须用同一个库。"""
    from fastapi.testclient import TestClient

    from app.config import reset_path_cache, resolve_database_path
    from app.db.engine import reset_engine
    from app.main import app

    monkeypatch.delenv("CVPLATFORM_DB_PATH", raising=False)
    monkeypatch.setenv("CVPLATFORM_ENV", "test")
    reset_engine()
    reset_path_cache()

    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/papers",
                json={
                    "title": "A Title In The Implicit Test Database",
                    "conference": "CVPR",
                    "year": 2024,
                },
            )
            assert created.status_code == 201, created.text
            listing = client.get("/api/papers")
            assert listing.status_code == 200
            assert listing.json()["total"] == 1
    finally:
        resolved = resolve_database_path()
        reset_engine()
        resolved.unlink(missing_ok=True)


# --------------------------------------------- 5. 含连字符标题的模糊查询


def test_fuzzy_query_matches_hyphenated_title(client, paper_factory):
    title = "Self-Supervised Learning for Vision Representation"
    paper_factory(title)

    assert client.get(
        "/api/papers", params={"q": title, "match": "exact"}
    ).json()["total"] == 1
    # 默认模糊查询必须与精确查询同样命中，不能因为连字符而归零
    assert client.get("/api/papers", params={"q": title}).json()["total"] == 1

    # 片段、大小写、连字符省略等写法都应收敛到同一条
    for query in [
        "self-supervised learning",
        "Self Supervised Learning",
        "SELF-SUPERVISED",
        "self supervised learning for vision",
    ]:
        found = client.get("/api/papers", params={"q": query}).json()
        assert found["total"] == 1, f"模糊查询未命中：{query!r}"


def test_fuzzy_query_still_matches_code_and_keyword(client, paper_factory):
    paper = paper_factory(
        "A Paper For Query Coverage Testing", source_keywords=["目标检测"]
    )
    assert paper["code"] == "CVPR-2024-0001"

    assert client.get("/api/papers", params={"q": "2024-0001"}).json()["total"] == 1
    code_hit = client.get("/api/papers", params={"q": "cvpr-2024-0001"}).json()
    assert code_hit["total"] == 1
    assert client.get("/api/papers", params={"q": "目标检测"}).json()["total"] == 1


def test_fuzzy_query_with_only_punctuation_does_not_crash(client, paper_factory):
    paper_factory("A Normal Paper With A Proper Title")
    # 归一化后为空串，不能生成意外的宽匹配，也不能报错
    response = client.get("/api/papers", params={"q": "---"})
    assert response.status_code == 200
    assert response.json()["total"] == 0


# ------------------------------------------- 6. 关键词读取的版本与去重


def test_keywords_only_return_current_version(client, paper_factory, temp_db):
    """重算后详情只能看到当前版本的词，不能混入上一版已淘汰的词。"""
    paper = paper_factory("A Paper That Gets Reprocessed By Keyword Rules")
    add_system_keyword(
        temp_db, paper_id=paper["id"], name="current version term", version="kw-v1"
    )
    add_system_keyword(
        temp_db, paper_id=paper["id"], name="retired old term", version="kw-v0"
    )

    detail = client.get(f"/api/papers/{paper['id']}").json()
    assert detail["system_keywords"] == ["current version term"]

    names = [item["name"] for item in detail["keywords"]]
    assert "retired old term" not in names
    assert "current version term" in names


def test_keywords_are_not_duplicated_across_versions(client, paper_factory, temp_db):
    """同一个词同时存在于两个版本时，标签只能出现一次。"""
    paper = paper_factory("A Paper With The Same Term In Two Versions")
    add_system_keyword(
        temp_db, paper_id=paper["id"], name="shared term", version="kw-v1"
    )
    add_system_keyword(
        temp_db, paper_id=paper["id"], name="shared term", version="kw-v0"
    )

    detail = client.get(f"/api/papers/{paper['id']}").json()
    assert detail["system_keywords"].count("shared term") == 1
    assert [item["name"] for item in detail["keywords"]].count("shared term") == 1


def test_author_keywords_survive_version_bump(client, paper_factory, temp_db):
    """作者关键词来自来源数据，与抽取规则版本无关，换版本后仍应展示。"""
    paper = paper_factory("An Author Keyword Paper", source_keywords=["来源关键词"])
    # 模拟规则版本升级：作者关键词的 ruleset_version 仍是写入时的旧值
    set_meta(temp_db, "keyword_ruleset_version", "kw-v2")

    detail = client.get(f"/api/papers/{paper['id']}").json()
    author_names = [
        item["name"] for item in detail["keywords"] if item["origin"] == "author"
    ]
    assert author_names == ["来源关键词"]


# --------------------------------------------------- 7. 状态筛选枚举校验


def test_invalid_status_filters_return_400(client):
    # 非空但不在枚举内的取值属于参数错误，不能静默返回空列表
    for params in ({"data_status": "published"}, {"keyword_status": "finished"}):
        response = client.get("/api/papers", params=params)
        assert response.status_code == 400, params
        detail = response.json()["detail"]
        assert detail["code"] == "invalid_parameter", params
        assert "状态" in detail["message"], params

    # 空串表示“不筛选”，属于合法请求
    for params in ({"data_status": ""}, {"keyword_status": ""}):
        assert client.get("/api/papers", params=params).status_code == 200, params


def test_valid_status_filters_still_work(client, paper_factory):
    paper_factory("A Paper For Status Filter Testing")
    for params in ({"data_status": "review"}, {"keyword_status": "pending"}):
        response = client.get("/api/papers", params=params)
        assert response.status_code == 200, params
        assert response.json()["total"] == 1


# ------------------------------------------- 8. 迁移模块不再有误导性复制函数


def test_migrations_module_has_no_file_copy_helper():
    """原先的 copy_database 注释称“在线备份”却直接复制主文件，WAL 下会丢数据，已删除。"""
    from app.db import migrations

    assert not hasattr(migrations, "copy_database")
    # 唯一被保留的复制途径是走在线备份接口
    assert hasattr(migrations, "backup_database")


def test_database_level_duplicate_key_is_reported_as_conflict(temp_db: Path):
    """数据库层的唯一索引是最后一道防线：即使绕过服务层，也不允许重复入库。"""
    import sqlite3

    import pytest

    insert_paper(temp_db, title="Title For Unique Index")
    with pytest.raises(sqlite3.IntegrityError):
        insert_paper(temp_db, code="CVPR-2024-0002", title="Title For Unique Index")
