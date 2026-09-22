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

from .config import DATASET_MIN_YEAR, HARVEST_SAMPLE_LIMIT, TARGET_CONFERENCE_YEARS
from .db.engine import init_database, session_scope
from .models.entities import CollectionTask
from .services import dataset_import, tasks
from .services.harvest import build_plans, create_harvest_tasks, describe_plan
from .services.sources import huggingface as hf


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


def _import_datasets(limit: int | None, min_year: int) -> int:
    """导入 HuggingFace 上的完整论文集（阶段 11 起作为主来源）。

    纳入前逐个校验摘要完整度；未达标的年份跳过并说明原因（例如会议数据仍在补齐）。
    """
    notes: list[str] = []
    print(f"发现数据集（{min_year} 年及以后，纳入前校验摘要完整度）…")
    refs = hf.discover(min_year=min_year, on_note=notes.append)
    for note in notes:
        print(f"  !! {note}")
    if not refs:
        print("没有可用数据集，请检查网络。")
        return 2

    covered = {(ref.conference, ref.year) for ref in refs}
    gaps = [item for item in TARGET_CONFERENCE_YEARS if item not in covered]
    print(f"可用数据集 {len(refs)} 个，合计 {sum(ref.rows for ref in refs)} 篇：")
    for ref in refs:
        print(f"  {ref.label}  摘要覆盖率 {ref.abstract_ratio:.0%}" if ref.abstract_ratio else f"  {ref.label}")
    if gaps:
        print(
            "以下目标组合没有数据集覆盖，将保留/继续使用抽样采集："
            + "、".join(f"{conf} {year}" for conf, year in gaps)
        )
    else:
        print("目标组合均被数据集覆盖，抽样采集结果会被同一去重键合并（不产生副本）。")

    total_created = total_updated = total_skipped = 0
    for ref in refs:
        with session_scope() as session:
            summary = dataset_import.import_dataset(session, ref, limit=limit)
        total_created += summary.created
        total_updated += summary.updated
        total_skipped += summary.skipped
        print(
            f"  {summary.label}：新建 {summary.created}、更新 {summary.updated}、"
            f"跳过 {summary.skipped}，用时 {summary.seconds}s"
            + (f"，修订 {summary.revision[:12]}" if summary.revision else "")
        )
        for title, reason in summary.failures[:3]:
            print(f"      跳过示例：{title[:60]} —— {reason}")
    print(
        f"全部完成：新建 {total_created}、更新 {total_updated}、跳过 {total_skipped}。"
        "接下来请运行 maintenance_cli process-keywords 重算关键词（语料已变化）。"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CVPlatform 真实数据采集")
    parser.add_argument("--plan", action="store_true", help="只打印抽样计划，不写库")
    parser.add_argument("--run", action="store_true", help="创建任务并开始处理")
    parser.add_argument(
        "--datasets",
        action="store_true",
        help="导入 HuggingFace 完整论文集（每会议年份全部论文，取代抽样爬取）",
    )
    parser.add_argument(
        "--min-year",
        type=int,
        default=DATASET_MIN_YEAR,
        help=f"数据集起始年份（默认 {DATASET_MIN_YEAR}）",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=HARVEST_SAMPLE_LIMIT,
        help=f"每个会议年份的抽样条数（默认 {HARVEST_SAMPLE_LIMIT}）",
    )
    args = parser.parse_args(argv)
    _configure_logging()

    if args.datasets:
        init_database()
        # --limit 用于试跑：只在显式传入且不是抽样默认值时生效
        dataset_limit = args.limit if args.limit != HARVEST_SAMPLE_LIMIT else None
        return _import_datasets(dataset_limit, args.min_year)

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
