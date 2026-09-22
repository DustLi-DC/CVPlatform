"""阶段 6 复核问题的回归用例。

每一组对应复核指出的一个缺陷，修复后必须长期有效。
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from sqlmodel import Session, select

from app.models.entities import CollectionTask, CollectionTaskItem, Paper
from app.services import adapters, importer, tasks
from app.services.index_cache import IndexCache, IndexedPaper
from app.services.papers import find_existing_paper, save_paper
from app.services.sources.cvf import PaperFields

# ------------------------------------------------ 1. 重启恢复覆盖全部任务


def test_recover_interrupted_requeues_every_resumable_task(temp_db: Path):
    """多个中断任务都要回到可继续状态，不能只起第一个。"""
    from app.db.engine import get_engine

    with Session(get_engine()) as session:
        ids = []
        for index in range(3):
            task = CollectionTask(
                kind="batch",
                file_name=f"interrupted-{index}.txt",
                file_format="txt",
                total_count=1,
                status="running",
                created_at="2026-01-01T00:00:00Z",
            )
            session.add(task)
            session.flush()
            session.add(
                CollectionTaskItem(
                    task_id=task.id or 0,
                    line_no=1,
                    input_title=f"Interrupted Paper Title Number {index}",
                    status="running",
                    created_at="2026-01-01T00:00:00Z",
                    updated_at="2026-01-01T00:00:00Z",
                )
            )
            ids.append(task.id or 0)
        session.commit()

    with Session(get_engine()) as session:
        recovered = tasks.recover_interrupted(session, auto_resume=True)
        session.commit()
        assert sorted(recovered) == sorted(ids)
        for task_id in ids:
            task = session.get(CollectionTask, task_id)
            assert task is not None
            # 自动续跑：直接回到待处理，交给执行器依次处理
            assert task.status == "pending", f"任务 {task_id} 未重新入队"
            assert task.pending_count == 1
            assert task.running_count == 0


def test_recover_without_auto_resume_keeps_interrupted(temp_db: Path):
    """关闭自动续跑时保持 interrupted，等待界面上的手动继续。"""
    from app.db.engine import get_engine

    with Session(get_engine()) as session:
        task = CollectionTask(
            kind="batch",
            file_name="manual.txt",
            file_format="txt",
            total_count=1,
            status="running",
            created_at="2026-01-01T00:00:00Z",
        )
        session.add(task)
        session.flush()
        session.add(
            CollectionTaskItem(
                task_id=task.id or 0,
                line_no=1,
                input_title="A Manual Resume Paper Title",
                status="running",
                created_at="2026-01-01T00:00:00Z",
                updated_at="2026-01-01T00:00:00Z",
            )
        )
        session.commit()
        task_id = task.id or 0

    with Session(get_engine()) as session:
        tasks.recover_interrupted(session, auto_resume=False)
        session.commit()
        task = session.get(CollectionTask, task_id)
        assert task is not None
        assert task.status == "interrupted"
        assert task.pending_count == 1


# -------------------------------------- 2. 跨会议年份同名论文不算重复


def test_same_title_in_different_conference_year_is_not_duplicate(temp_db: Path):
    from app.db.engine import get_engine

    title = "Visual Prompt Tuning"
    with Session(get_engine()) as session:
        save_paper(session, title=title, conference="ECCV", year=2022, abstract="A.")
        session.commit()

    with Session(get_engine()) as session:
        # 同一题目在另一个会议年份：不是重复
        assert (
            find_existing_paper(session, title=title, conference="CVPR", year=2025)
            is None
        )
        # 同一会议年份才是重复
        assert (
            find_existing_paper(session, title=title, conference="ECCV", year=2022)
            is not None
        )
        # 会议年份未知时才按标题全等兜底
        assert find_existing_paper(session, title=title) is not None


def test_csv_in_file_dedup_respects_conference_and_year():
    content = chr(10).join(
        [
            "title,conference,year",
            "A Shared Dataset Paper Title,CVPR,2024",
            "A Shared Dataset Paper Title,ICCV,2023",  # 同名不同会议年份
            "A Shared Dataset Paper Title,CVPR,2024",  # 真正的重复
        ]
    )
    result = importer.parse_file("papers.csv", content.encode())
    assert result.valid_count == 2
    assert result.duplicate_in_file_count == 1
    duplicate = [row for row in result.rows if row.status == "duplicate_in_file"]
    assert duplicate[0].line_no == 4


# ------------------------------------------ 3. 索引匹配不得扩大范围


def test_match_with_unknown_combination_does_not_search_other_years():
    """指定了会议年份但该组合索引未载入时，必须返回未命中，不能匹配其他年份。"""
    cache = IndexCache()
    entry = IndexedPaper(
        title="Some CVPR Paper Title",
        conference="CVPR",
        year=2024,
        paper_path="/p/1",
        landing_url="https://example.org/1",
    )
    cache._entries[("CVPR", 2024)] = [entry]
    cache._by_normalized[("CVPR", 2024)] = {"some cvpr paper title": entry}

    hit, score = cache.match("Some CVPR Paper Title", conference="ICCV", year=2025)
    assert hit is None, "指定 ICCV 2025 时不应返回 CVPR 2024 的条目"
    assert score == 0.0

    # 不指定组合时才在全部已缓存组合里找
    hit_any, score_any = cache.match("Some CVPR Paper Title")
    assert hit_any is not None and score_any == 1.0


def test_fuzzy_index_hit_requires_confirmation(client, monkeypatch, temp_db: Path):
    """索引里只有相近条目时不能自动入库，要保留人工确认。"""
    from app.services.sources.cvf import IndexEntry

    index_entry = IndexEntry(
        title="Attention Is All You Need For Vision Tasks",
        paper_path="/content/CVPR2024/html/similar_paper.html",
    )
    monkeypatch.setattr(
        "app.services.index_cache.cvf.fetch_index",
        lambda conference, year, **kwargs: [index_entry],
    )
    monkeypatch.setattr("app.services.tasks.shared_cache", IndexCache())

    content = chr(10).join(["title,conference,year", "Attention Is All You Need For Vision,CVPR,2024", ""])
    task = client.post(
        "/api/import/tasks",
        files={"file": ("fuzzy.csv", io.BytesIO(content.encode()), "text/csv")},
    ).json()

    import time

    deadline = time.monotonic() + 20
    payload = {}
    while time.monotonic() < deadline:
        payload = client.get(f"/api/import/tasks/{task['id']}").json()
        if payload["status"] in ("success", "partial", "failed", "interrupted"):
            break
        time.sleep(0.1)

    assert payload["success_count"] == 0, payload
    assert payload["failed_count"] == 1, payload
    detail = client.get(f"/api/import/tasks/{task['id']}").json()
    message = detail["items"][0]["message"] or ""
    assert "人工确认" in message
    assert "Attention Is All You Need For Vision Tasks" in message
    assert client.get("/api/papers").json()["total"] == 0


# --------------------------------------------- 4. CSV 错误处理


def test_long_csv_field_returns_validation_error():
    """字段超过 csv 模块上限时应返回清楚的校验错误，而不是未捕获异常。"""
    import csv as csv_module

    too_long = "A" * (csv_module.field_size_limit() + 10)
    content = f'title,conference,year{chr(10)}"{too_long}",CVPR,2024{chr(10)}'
    with pytest.raises(importer.ImportFileError) as error:
        importer.parse_file("papers.csv", content.encode())
    assert error.value.code == "invalid_csv"
    assert "CSV" in error.value.message


def test_blank_lines_do_not_shift_reported_row_numbers():
    """空行不算数据行，报告的行号必须是文件里的物理行号。"""
    lines = [
        "title,conference,year",
        "",  # 物理第 2 行
        "A Valid CSV Paper Title,CVPR,2024",  # 物理第 3 行
        "",  # 物理第 4 行
        "An Invalid CSV Paper Title,NOTACONF,2024",  # 物理第 5 行
    ]
    result = importer.parse_file("papers.csv", chr(10).join(lines).encode())
    invalid = [row for row in result.rows if row.status == "invalid"]
    assert invalid and invalid[0].line_no == 5, [row.line_no for row in result.rows]


def test_txt_blank_lines_keep_physical_row_numbers():
    lines = ["", "A Valid TXT Paper Title Here", "", "短", ""]
    result = importer.parse_file("titles.txt", chr(10).join(lines).encode())
    # 末尾换行不产生新行，因此是 2 个空行
    assert result.blank_count == 2
    invalid = [row for row in result.rows if row.status == "invalid"]
    assert invalid[0].line_no == 4


# ----------------------------------- 5. 适配器保留关键词来源与采集时间


def test_adapter_keeps_keyword_origin_and_original_source(temp_db: Path):
    """数据集自带的关键词写为系统提取；原始来源与采集时间保留，不被覆盖。"""
    from app.db.engine import get_engine

    record = adapters.DatasetRecord(
        title="A Dataset Paper With System Keywords",
        conference="CVPR",
        year=2024,
        abstract="An abstract from the dataset.",
        keywords=["作者给出的词"],
        system_keywords=["object detection", "attention"],
        source="cvf",
        source_id="dataset-1",
        retrieved_at="2026-09-01T00:00:00Z",
    )
    with Session(get_engine()) as session:
        result = adapters.import_records(session, [record])
        session.commit()
        assert result.created == 1

    with Session(get_engine()) as session:
        paper = session.exec(select(Paper)).one()
        assert paper.primary_source == "cvf", "原始来源不能被写成 dataset"
        assert paper.retrieved_at == "2026-09-01T00:00:00Z", "采集时间应保留"
        assert paper.keyword_status == "done"

    detail = None
    from app.routers.papers import _to_detail
    from app.services import papers as paper_service

    with Session(get_engine()) as session:
        paper = session.exec(select(Paper)).one()
        keyword_map = paper_service.load_paper_keywords(session, [paper.id or 0])
        sources = paper_service.load_paper_sources(session, [paper.id or 0])
        detail = _to_detail(paper, keyword_map.get(paper.id or 0, []), sources.get(paper.id or 0, []))
        session.commit()

    origin_by_name = {item.name: item.origin for item in detail.keywords}
    assert origin_by_name["object detection"] == "system"
    assert origin_by_name["attention"] == "system"
    assert origin_by_name["作者给出的词"] == "author"


def test_shipped_sample_imports_without_changing_origin(temp_db: Path):
    """仓库里的小样例导入后，系统关键词仍是系统关键词，来源仍是 cvf。"""
    from app.db.engine import get_engine

    sample_path = Path(__file__).resolve().parents[2] / "deploy" / "sample" / "cvplatform_sample.json"
    records = adapters.load_records(sample_path)
    assert records, "样例文件应能解析出记录"
    for record in records:
        assert record.system_keywords, f"{record.title} 的样例缺少 system_keywords"
        assert record.source and record.source != "dataset"
        assert record.retrieved_at

    with Session(get_engine()) as session:
        result = adapters.import_records(session, records)
        session.commit()
        assert result.created == len(records)

    with Session(get_engine()) as session:
        sources = {paper.primary_source for paper in session.exec(select(Paper)).all()}
        # 样例跨两个来源：CVPR/ICCV 来自 CVF，ECCV 来自 ECVA
        assert sources <= {"cvf", "ecva"} and sources, sources
