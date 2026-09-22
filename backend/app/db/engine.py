"""数据库引擎与会话管理。

- 单 worker 场景，SQLite 单写者：写操作经同一会话工厂，并设置 busy_timeout。
- 每个连接都显式开启 foreign_keys，否则 SQLite 不会执行级联删除。
- journal_mode=WAL 由 migrations.initialize_database 在初始化时设置并持久化。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, create_engine

from ..config import load_settings
from .migrations import initialize_database

_engine: Engine | None = None


def _configure_connection(dbapi_connection, _connection_record) -> None:
    """每个新连接都设置外键与忙等待，保证级联删除与并发写的行为可预期。"""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA busy_timeout = 5000")
    finally:
        cursor.close()


def get_engine() -> Engine:
    """进程内共用一个引擎；路径由 config.resolve_database_path 决定。"""
    global _engine
    if _engine is None:
        settings = load_settings()
        settings.database_path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{settings.database_path.as_posix()}",
            echo=False,
            connect_args={"check_same_thread": False},
        )
        event.listen(_engine, "connect", _configure_connection)
    return _engine


def reset_engine() -> None:
    """丢弃缓存的引擎；测试在切换数据库路径后需要调用。

    刻意不清空 config 的路径缓存：清空会让“初始化用的库”与“查询用的库”变成两个
    不同的临时文件（见 config._default_test_database_path）。
    确实需要重新解析路径时，调用方显式调用 config.reset_path_cache()。
    """
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None


@contextmanager
def session_scope() -> Iterator[Session]:
    """事务作用域：正常提交，异常回滚，最后一定关闭。"""
    session = Session(get_engine())
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_database() -> dict[str, object]:
    """启动时初始化或升级数据库，可重复调用。"""
    settings = load_settings()
    summary = initialize_database(settings.database_path)
    reset_engine()
    return summary
