#!/usr/bin/env python3
"""把发布目录里的文本文件统一成 LF 行尾。

为什么需要它：开发机是 Windows，工作区的文件是 CRLF；如果直接把工作区打包，
服务器上的 bash 会把行尾的 CR 当成命令的一部分，报
`$'\r': command not found`（阶段 11 首次上传时实际踩到）。

用法：
    python deploy/normalize_eol.py <目录>        # 就地归一化
    python deploy/normalize_eol.py <目录> --check  # 只检查，发现 CRLF 时以非零状态退出
"""

from __future__ import annotations

import sys
from pathlib import Path

# 需要归一化的文本类型：脚本、Python、数据与文档、配置模板
SUFFIXES = {
    ".sh",
    ".py",
    ".json",
    ".md",
    ".txt",
    ".example",
    ".conf",
    ".cfg",
    ".service",
    # 前端源码也按 LF 维护（.gitattributes 为 * text=auto eol=lf）
    ".ts",
    ".vue",
    ".css",
    ".html",
    ".js",
    ".mjs",
}


def targets(root: Path) -> list[Path]:
    return [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and (path.suffix in SUFFIXES or path.name.endswith(".example"))
    ]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    root = Path(argv[1])
    check_only = "--check" in argv
    if not root.is_dir():
        print(f"目录不存在：{root}")
        return 2

    changed: list[Path] = []
    for path in targets(root):
        data = path.read_bytes()
        if b"\r\n" not in data:
            continue
        changed.append(path)
        if not check_only:
            path.write_bytes(data.replace(b"\r\n", b"\n"))

    if check_only:
        if changed:
            print("以下文件含 CRLF 行尾：")
            for path in changed:
                print(f"  - {path.relative_to(root)}")
            return 1
        print(f"检查通过：{len(targets(root))} 个文本文件均为 LF")
        return 0

    print(f"归一化 {len(changed)} 个文件为 LF（检查 {len(targets(root))} 个）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
