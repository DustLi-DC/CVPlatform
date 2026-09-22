"""测试夹具：每个用例使用独立的临时数据库，绝不触碰开发或生产数据。

设计依据：阶段 3 任务第 7 条——以独立测试数据库验证，不得操作用户生产数据。
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

# 让测试可以直接 import app.*，无需安装包
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture()
def temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """把数据库指向本次用例独有的临时文件，并完成初始化。"""
    db_path = tmp_path / "cvplatform-test.db"
    monkeypatch.setenv("CVPLATFORM_ENV", "test")
    monkeypatch.setenv("CVPLATFORM_DB_PATH", str(db_path))

    from app.db.engine import init_database, reset_engine

    reset_engine()
    init_database()
    yield db_path
    reset_engine()


@pytest.fixture()
def client(temp_db: Path) -> Iterator["TestClient"]:  # noqa: F821
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def paper_factory(client):
    """便捷地创建论文，返回响应 JSON。"""

    def create(
        title: str,
        conference: str = "CVPR",
        year: int = 2024,
        *,
        abstract: str | None = "一段用于测试的摘要文本。",
        source_keywords: list[str] | None = None,
        expect: int = 201,
    ) -> dict:
        response = client.post(
            "/api/papers",
            json={
                "title": title,
                "conference": conference,
                "year": year,
                "abstract": abstract,
                "source_keywords": source_keywords or [],
            },
        )
        assert response.status_code == expect, response.text
        return response.json()

    return create
