"""真实数据采集的命令行入口。

用法（在仓库根目录，用项目虚拟环境执行）：

    ./.venv/Scripts/python.exe -m app.harvest_cli --plan          # 只打印抽样计划
    ./.venv/Scripts/python.exe -m app.harvest_cli --run           # 创建任务并处理
    ./.venv/Scripts/python.exe -m app.harvest_cli --run --limit 50

以 `python -m app.harvest_cli` 运行时，模块路径需包含 backend，
因此实际调用方式见 数据覆盖与来源.md 中记录的复现命令。

设计要点：
- 抽样规则确定且可复现（步长 = 索引总数 // 目标条数），逐条落库；
- 任务可中断续跑：已入库条目标记为重复，重复运行不会产生重复记录；
- 低并发：走全局限速器，单线程顺序处理。
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import HARVEST_SAMPLE_LIMIT, TARGET_CONFERENCE_YEARS
from .db.engine import init_database, session_scope
from .models.entities import CollectionTask
from .services import tasks
from .services.harvest import build_plans, create_harvest_tasks, describe_plan


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def _print_plans(limit: int) -> list:
    """打印每个组合的抽样计划，便于先核对再执行。"""
    def on_error(conference: str, year: int, error: Exception) -> None:
        print(f"  !! {conference} {year} 索引载入失败：{error}")

    plans = build_plans(limit=limit, on_error=on_error)
    print(f"目标组合：{len(TARGET_CONFERENCE_YEARS)} 个，每个 {limit} 条")
    for plan in plans:
        print("  " + describe_plan(plan))
    return plans


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CVPlatform 真实数据采集")
    parser.add_argument("--plan", action="store_true", help="只打印抽样计划，不写库")
    parser.add_argument("--run", action="store_true", help="创建任务并开始处理")
    parser.add_argument(
        "--limit",
        type=int,
        default=HARVEST_SAMPLE_LIMIT,
        help=f"每个会议年份的抽样条数（默认 {HARVEST_SAMPLE_LIMIT}）",
    )
    args = parser.parse_args(argv)
    _configure_logging()

    if not args.plan and not args.run:
        parser.print_help()
        return 1

    init_database()

    if args.plan:
        _print_plans(args.limit)
        if not args.run:
            return 0

    plans = _print_plans(args.limit) if not args.plan else build_plans(limit=args.limit)
    if not plans:
        print("没有可用的抽样计划，请检查网络与来源可用性。")
        return 2

    with session_scope() as session:
        task_ids = create_harvest_tasks(session, plans)
        print(f"已创建 {len(task_ids)} 个采集任务：{task_ids}")

    if not args.run:
        return 0

    # 前台逐个处理：便于观察进度；中断后重新执行同一命令即可续跑
    for task_id in task_ids:
        tasks.runner.run_sync(task_id)
        with session_scope() as session:
            task = session.get(CollectionTask, task_id)
            if task is not None:
                print(
                    f"任务 {task_id}（{task.file_name}）状态 {task.status}："
                    f"成功 {task.success_count}、重复 {task.duplicate_count}、"
                    f"失败 {task.failed_count}"
                )
    return 0


if __name__ == "__main__":
    sys.exit(main())
