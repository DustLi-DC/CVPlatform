#!/usr/bin/env python3
"""数据库在线备份脚本。

统一使用 SQLite 在线备份接口（Connection.backup）：
数据库启用 WAL 后，已提交的数据可能仍在 -wal 文件中，直接复制主文件会得到
不完整或与实际不一致的备份。在线备份接口会读出包含 WAL 内容的一致快照，
且不需要停止服务、不需要按文件大小分情况处理。

用法：
    python deploy/backup_database.py [数据库路径] [备份目录]

若不传参数，读取环境变量 CVPLATFORM_DB_PATH；
仍未设置时按 CVPLATFORM_ENV 决定默认路径（生产为 /var/lib/cvplatform/cvplatform.db）。
备份目录默认是数据库同级的 backups/ 子目录，也可用 CVPLATFORM_BACKUP_DIR 覆盖。
"""

from __future__ import annotations

import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_PRODUCTION_PATH = Path("/var/lib/cvplatform/cvplatform.db")
DEFAULT_BACKUP_DIR_NAME = "backups"
# 保留的备份份数，超出后删除最旧的
KEEP_BACKUPS = 10
# 备份文件名：{数据库名}-{UTC 时间戳}.db
TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"


def resolve_source(arg: str | None) -> Path:
    if arg:
        return Path(arg).expanduser().resolve()
    from_env = os.environ.get("CVPLATFORM_DB_PATH", "").strip()
    if from_env:
        return Path(from_env).expanduser().resolve()
    if os.environ.get("CVPLATFORM_ENV", "").strip().lower() == "production":
        return DEFAULT_PRODUCTION_PATH
    raise SystemExit("未指定数据库路径：请传入参数或设置 CVPLATFORM_DB_PATH 环境变量。")


def resolve_target_dir(source: Path, arg: str | None) -> Path:
    """解析备份目录。

    这里刻意不用 `Path(参数 or 环境变量 or 默认值)` 的紧凑写法：`Path("")` 会被解析成
    当前目录且为真值，会让默认值失效、把备份写进当前工作目录。必须先判空再构造 Path。
    """
    candidate = (arg or "").strip()
    if not candidate:
        candidate = os.environ.get("CVPLATFORM_BACKUP_DIR", "").strip()
    if candidate:
        return Path(candidate).expanduser().resolve()
    return source.parent / DEFAULT_BACKUP_DIR_NAME


def backup_name_pattern(source: Path) -> re.Pattern[str]:
    """本脚本为指定数据库生成的备份文件名模式。"""
    return re.compile(
        rf"^{re.escape(source.stem)}-\d{{8}}T\d{{6}}Z\.db$"
    )


def make_backup(source: Path, target_dir: Path) -> Path:
    if not source.exists():
        raise SystemExit(f"数据库不存在：{source}")

    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime(TIMESTAMP_FORMAT)
    target = target_dir / f"{source.stem}-{stamp}.db"

    origin = sqlite3.connect(source)
    try:
        destination = sqlite3.connect(target)
        try:
            origin.backup(destination)
        finally:
            destination.close()
    finally:
        origin.close()

    # 备份后立刻做一次完整性检查，避免留下不可用的备份
    verification = sqlite3.connect(target)
    try:
        result = verification.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        verification.close()
    if result != "ok":
        target.unlink(missing_ok=True)
        raise SystemExit(f"备份完整性检查失败：{result}")

    return target


def prune(target_dir: Path, source: Path, keep: int) -> list[Path]:
    """只清理本脚本为同一个数据库生成的备份。

    使用严格的 `{数据库名}-时间戳.db` 模式，而不是宽泛的 `*.db`：
    备份目录里可能同时存在其他数据库或文件（例如误把备份目录设为某个数据目录），
    宽泛匹配会连无关文件一起删掉。
    """
    pattern = backup_name_pattern(source)
    candidates = [
        item
        for item in target_dir.iterdir()
        if item.is_file() and pattern.match(item.name)
    ]
    candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)

    removed: list[Path] = []
    for stale in candidates[keep:]:
        stale.unlink()
        removed.append(stale)
    return removed


def main(argv: list[str]) -> int:
    source = resolve_source(argv[1] if len(argv) > 1 else None)
    target_dir = resolve_target_dir(source, argv[2] if len(argv) > 2 else None)

    backup = make_backup(source, target_dir)
    removed = prune(target_dir, source, KEEP_BACKUPS)

    print(f"源数据库：{source}")
    print(f"备份目录：{target_dir}")
    print(f"备份文件：{backup}（{backup.stat().st_size} 字节，完整性检查通过）")
    for stale in removed:
        print(f"已清理旧备份：{stale}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
