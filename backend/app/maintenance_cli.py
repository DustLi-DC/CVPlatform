"""统计与关键词的维护命令入口。

用法（在仓库根目录，用项目虚拟环境执行）：

    ./.venv/Scripts/python.exe -m app.maintenance_cli status
    ./.venv/Scripts/python.exe -m app.maintenance_cli fix-entities            # 试运行
    ./.venv/Scripts/python.exe -m app.maintenance_cli fix-entities --apply
    ./.venv/Scripts/python.exe -m app.maintenance_cli process-keywords [--limit N]
    ./.venv/Scripts/python.exe -m app.maintenance_cli reload-topics

模块路径需包含 backend，因此实际调用方式为
`PYTHONPATH=backend ./.venv/Scripts/python.exe -m app.maintenance_cli ...`，
与 数据覆盖与来源.md 中记录的复现命令一致。
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from sqlalchemy import text

from .db.engine import init_database, session_scope
from .services import keyword_job, maintenance, topic_layer


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def _status() -> int:
    with session_scope() as session:
        counts = keyword_job.status_counts(session)
        print(f"分析集合分母：{counts['analysis_papers']}")
        print(f"语料集合：{counts['corpus_papers']}")
        print(f"关键词状态：{counts['by_status']}")
        print(f"待处理（含待重算）：{counts['pending_or_stale']}")
        print(f"关键词规则版本：{counts['ruleset_version']}")
        print(f"分析集合版本：{maintenance.read_analysis_version(session)}")
        print(f"系统关键词：{counts['system_keywords']}，已映射主题：{counts['mapped_keywords']}")
    return 0


def _fix_entities(apply: bool) -> int:
    with session_scope() as session:
        result = maintenance.repair_html_entities(session, apply=apply)
    mode = "已写入" if result["applied"] else "试运行（未写入）"
    print(f"{mode}：检查 {result['scanned']} 篇，需要修复 {result['changed']} 篇")
    print(f"实体替换统计：{result['entity_kinds']}")
    for sample in result["samples"]:
        print(f"  {sample['code']} 修复前 …{sample['before']}…")
        print(f"  {sample['code']} 修复后 …{sample['after']}…")
    return 0


def _process_keywords(limit: int | None, force: bool) -> int:
    started = time.perf_counter()
    with session_scope() as session:
        summary = keyword_job.process_pending(session, limit=limit, force=force)
    elapsed = time.perf_counter() - started
    print(
        f"处理完成：语料 {summary.corpus_size} 篇，已处理 {summary.processed}，"
        f"其中关键词为空 {summary.empty}，失败 {summary.failed}，剩余 {summary.remaining}"
    )
    print(
        f"参数：min_df={summary.effective_min_df}、短语启用={summary.phrases_enabled}、"
        f"配置签名={summary.config_signature}"
    )
    print(f"耗时 {elapsed:.1f}s（{elapsed / max(1, summary.processed):.3f}s/篇）")
    return 0


def _reload_topics() -> int:
    with session_scope() as session:
        result = topic_layer.sync_topics(session)
    print(
        f"主题表 {result['topic_version']}：主题 {result['topics']} 个"
        f"（新增 {result['created']}、更新 {result['updated']}、停用 {result['deactivated']}）、"
        f"别名写入 {result['aliases']}、已映射关键词 {result['mapped_keywords']}"
    )
    return 0


def _import_dataset(path_text: str) -> int:
    """导入课程数据集 / 可分发样例（JSON），复用统一的清洗、去重与关键词逻辑。"""
    from pathlib import Path as _Path

    from .services import adapters

    path = _Path(path_text).expanduser().resolve()
    if not path.exists():
        print(f"文件不存在：{path}")
        return 1
    records = adapters.load_records(path)
    with session_scope() as session:
        result = adapters.import_records(session, records)
    print(
        f"导入完成：共 {result.total} 条，新建 {result.created}，更新 {result.updated}，"
        f"跳过 {result.skipped}"
    )
    for title, reason in result.failures[:10]:
        print(f"  跳过：{title[:60]} —— {reason}")
    return 0


def _verify_stats(top: int, repeats: int) -> int:
    """用独立写的 SQL 复算统计结果，并测量各接口的耗时与内存峰值。

    复算路径**刻意不用** v_analysis_paper / v_analysis_keyword 两个视图，
    而是把分析集合条件逐条写开（会议年份有效、标题可用、关键词已完成且版本为当前版本、
    只算系统关键词）。这样既能核对数字，也能反查视图本身是否写对。
    """
    import sqlite3
    import time as clock
    import tracemalloc

    from .config import resolve_database_path
    from .services import stats as stats_service

    db_path = resolve_database_path()
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    ruleset_row = connection.execute(
        "SELECT value FROM meta WHERE key = 'keyword_ruleset_version'"
    ).fetchone()
    ruleset = ruleset_row[0] if ruleset_row else ""
    analysis_condition = (
        "p.conference IN ('CVPR','ICCV','ECCV') AND p.year > 0 "
        "AND length(p.title_normalized) >= 4 AND p.keyword_status = 'done' "
        "AND p.keyword_ruleset_version = ?"
    )
    independent_denominator = connection.execute(
        f"SELECT COUNT(*) FROM paper p WHERE {analysis_condition}", (ruleset,)
    ).fetchone()[0]

    top_sql = f"""
        SELECT COALESCE(t.slug, '__unmapped__') AS key,
               COALESCE(t.name, '未归类') AS name,
               COUNT(DISTINCT p.id) AS papers
          FROM paper p
          JOIN paper_keyword pk ON pk.paper_id = p.id AND pk.ruleset_version = ?
          JOIN keyword k ON k.id = pk.keyword_id AND k.origin = 'system'
          LEFT JOIN topic t ON t.id = k.topic_id AND t.is_active = 1
         WHERE {analysis_condition} AND t.id IS NOT NULL
         GROUP BY key
         ORDER BY papers DESC, key ASC
         LIMIT ?
    """
    independent_top = [
        (row["key"], row["name"], row["papers"])
        for row in connection.execute(top_sql, (ruleset, ruleset, top)).fetchall()
    ]
    # 未归类单独复算：它不参与榜单排序，但要与服务给出的规模对得上
    independent_unmapped = connection.execute(
        "SELECT COUNT(DISTINCT p.id) FROM paper p "
        "JOIN paper_keyword pk ON pk.paper_id = p.id AND pk.ruleset_version = ? "
        "JOIN keyword k ON k.id = pk.keyword_id AND k.origin = 'system' "
        f"WHERE {analysis_condition} AND k.topic_id IS NULL",
        (ruleset, ruleset),
    ).fetchone()[0]

    # 图谱边权：用 SQL 自连接统计同篇共现，与服务的 Python 成对计数互为校验
    pair_from = f"""
        SELECT pk.paper_id AS paper_id, COALESCE(t.slug,'__unmapped__') AS key
          FROM paper p
          JOIN paper_keyword pk ON pk.paper_id = p.id AND pk.ruleset_version = ?
          JOIN keyword k ON k.id = pk.keyword_id AND k.origin = 'system'
          LEFT JOIN topic t ON t.id = k.topic_id AND t.is_active = 1
         WHERE {analysis_condition}
    """
    edge_sql = f"""
        SELECT a.key AS left_key, b.key AS right_key, COUNT(DISTINCT a.paper_id) AS weight
          FROM ({pair_from}) a
          JOIN ({pair_from}) b ON a.paper_id = b.paper_id AND a.key < b.key
         WHERE a.key != '__unmapped__' AND b.key != '__unmapped__'
         GROUP BY a.key, b.key
         ORDER BY weight DESC, a.key, b.key
    """
    independent_edges = [
        (row["left_key"], row["right_key"], row["weight"])
        for row in connection.execute(
            edge_sql, (ruleset, ruleset, ruleset, ruleset)
        ).fetchall()
    ]
    connection.close()

    print(f"数据库：{db_path}")
    print(f"规则版本：{ruleset}")
    print()

    with session_scope() as session:
        service_summary = stats_service.summary(session, stats_service.parse_scope())
        service_top = stats_service.top(session, stats_service.parse_scope(), limit=top)
        service_graph = stats_service.graph(
            session, stats_service.parse_scope(), limit=200, min_edge=1
        )

    mismatches = 0
    print(f"分母：服务 {service_summary['denominator']} | 独立 SQL {independent_denominator}")
    if service_summary["denominator"] != independent_denominator:
        print("  !! 分母不一致")
        mismatches += 1

    service_items = [
        (item["key"], item["name"], item["count"])
        for item in service_top["items"]
        if not item["is_unmapped"]
    ][:top]
    print(f"\nTop {top}（独立 SQL 复算）：")
    for index, (row, expected) in enumerate(zip(service_items, independent_top), start=1):
        same = row == expected
        if not same:
            mismatches += 1
        flag = "" if same else f"   !! 服务给出 {row}"
        print(f"  {index:2d}. {expected[1]:16s} {expected[2]:4d}{flag}")
    print(
        f"  未归类：服务 {service_top['unmapped']['paper_count']} 篇 | "
        f"独立 SQL {independent_unmapped} 篇"
    )
    if service_top["unmapped"]["paper_count"] != independent_unmapped:
        print("  !! 未归类规模不一致")
        mismatches += 1

    service_edges = sorted(
        (edge["source"], edge["target"], edge["weight"]) for edge in service_graph["edges"]
    )
    print(f"\n图谱：服务 {len(service_edges)} 条边 | 独立 SQL {len(independent_edges)} 条边")
    if service_edges == sorted(independent_edges):
        print("  边集合与权重完全一致（含同篇共现去重计数）")
    else:
        mismatches += 1
        print("  !! 边集合或权重不一致")
        print(f"     服务：{service_edges[:3]}")
        print(f"     独立：{sorted(independent_edges)[:3]}")

    with session_scope() as session:
        duplicates = session.execute(
            text(
                "SELECT p.code AS code, COALESCE(t.name,'未归类') AS topic, COUNT(*) AS hits "
                "FROM paper p "
                "JOIN paper_keyword pk ON pk.paper_id = p.id "
                "JOIN keyword k ON k.id = pk.keyword_id "
                "LEFT JOIN topic t ON t.id = k.topic_id "
                "GROUP BY p.id, t.id HAVING hits > 1 LIMIT 3"
            )
        ).all()
    print(
        f"\n同一篇论文多次命中同一主题的样本：{len(duplicates)} 例"
        "（去重计数会把它算作一篇）"
    )
    for row in duplicates:
        print(f"  {row[0]} 命中 {row[1]} {row[2]} 次")

    print("\n接口耗时（冷启动 / 缓存命中，取多轮最小值）：")
    with session_scope() as session:
        for name, call in (
            ("summary", lambda: stats_service.summary(session, stats_service.parse_scope())),
            ("top", lambda: stats_service.top(session, stats_service.parse_scope())),
            ("graph", lambda: stats_service.graph(session, stats_service.parse_scope())),
            ("trend", lambda: stats_service.trend(session, stats_service.parse_scope())),
        ):
            cold_best = warm_best = None
            for _ in range(repeats):
                stats_service.clear_cache()
                started = clock.perf_counter()
                call()
                cold = clock.perf_counter() - started
                started = clock.perf_counter()
                call()
                warm = clock.perf_counter() - started
                cold_best = cold if cold_best is None else min(cold_best, cold)
                warm_best = warm if warm_best is None else min(warm_best, warm)
            print(
                f"  {name:8s} 冷 {cold_best * 1000:7.1f} ms | "
                f"缓存命中 {warm_best * 1000:6.2f} ms"
            )

    tracemalloc.start()
    with session_scope() as session:
        stats_service.clear_cache()
        stats_service.graph(session, stats_service.parse_scope(), limit=200, min_edge=1)
        _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"  图谱（节点上限 200）内存峰值：{peak / 1024 / 1024:.2f} MB")

    print()
    if mismatches:
        print(f"核对未通过：{mismatches} 处不一致")
        return 2
    print("核对通过：分母、Top 榜与图谱边权均与服务返回一致")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CVPlatform 统计与关键词维护")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="打印分析集合与关键词状态")
    fix = sub.add_parser("fix-entities", help="修复摘要中残留的 HTML 实体")
    fix.add_argument("--apply", action="store_true", help="真正写入（默认只试运行）")
    process = sub.add_parser("process-keywords", help="按需处理待处理或待重算的论文")
    process.add_argument("--limit", type=int, default=None, help="本次最多处理多少篇")
    process.add_argument("--force", action="store_true", help="忽略状态与版本，对语料全量重算")
    sub.add_parser("reload-topics", help="重新载入主题表并重算关键词的主题映射")
    dataset = sub.add_parser("import-dataset", help="导入课程数据集或可分发样例（JSON）")
    dataset.add_argument("path", help="数据集文件路径，如 deploy/sample/cvplatform_sample.json")
    verify = sub.add_parser("verify-stats", help="用独立 SQL 复算统计结果并测量耗时内存")
    verify.add_argument("--top", type=int, default=10, help="复算的榜单条数")
    verify.add_argument("--repeats", type=int, default=3, help="耗时测量轮数")

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 1

    _configure_logging()
    init_database()

    if args.command == "status":
        return _status()
    if args.command == "fix-entities":
        return _fix_entities(args.apply)
    if args.command == "process-keywords":
        return _process_keywords(args.limit, args.force)
    if args.command == "reload-topics":
        return _reload_topics()
    if args.command == "import-dataset":
        return _import_dataset(args.path)
    if args.command == "verify-stats":
        return _verify_stats(args.top, args.repeats)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
