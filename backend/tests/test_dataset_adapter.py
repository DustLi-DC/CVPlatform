"""完整字段数据集适配器的验证（阶段 6 任务第 8 条）。

重点：适配器必须复用统一的校验、去重与关键词逻辑，而不是另走一条写入路径。
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlmodel import Session

from app.services import adapters
from app.services.papers import save_paper


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_load_json_dataset_with_full_fields(tmp_path: Path):
    path = _write(
        tmp_path,
        "dataset.json",
        json.dumps(
            {
                "papers": [
                    {
                        "title": "Unmixing Diffusion for Hyperspectral Image Denoising",
                        "conference": "CVPR",
                        "year": 2024,
                        "abstract": "An abstract from the dataset.",
                        "authors": ["Haijin Zeng", "Jiezhang Cao"],
                        "keywords": ["hyperspectral", "denoising"],
                        "landing_url": "https://example.org/a",
                        "pdf_url": "https://example.org/a.pdf",
                        "source": "teacher_dataset",
                        "id": "T-0001",
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )
    records = adapters.load_records(path)
    assert len(records) == 1
    record = records[0]
    assert record.conference == "CVPR"
    assert record.year == 2024
    assert record.authors == ["Haijin Zeng", "Jiezhang Cao"]
    assert record.keywords == ["hyperspectral", "denoising"]
    assert record.source == "teacher_dataset"
    assert record.source_id == "T-0001"
    assert record.problems == []


def test_load_csv_dataset_accepts_chinese_headers(tmp_path: Path):
    path = _write(
        tmp_path,
        "dataset.csv",
        "题目,会议,年份,摘要,关键词\n"
        "A Complete Dataset Paper Title,ICCV,2023,摘要内容,目标检测；视觉语言模型\n",
    )
    records = adapters.load_records(path)
    assert len(records) == 1
    assert records[0].conference == "ICCV"
    assert records[0].year == 2023
    # 中文分号不在分隔符里，应按逗号/中文逗号切分——这里断言至少不丢内容
    assert records[0].keywords


def test_records_with_missing_fields_are_skipped(tmp_path: Path):
    path = _write(
        tmp_path,
        "broken.json",
        json.dumps(
            [
                {"title": "A Paper Without Conference Or Year"},
                {"title": "短", "conference": "CVPR", "year": 2024},
                {
                    "title": "A Paper With Unknown Venue",
                    "conference": "WACV",
                    "year": 2024,
                },
            ]
        ),
    )
    records = adapters.load_records(path)

    # 缺会议年份的记录本身不算「字段有问题」，但导入时会被跳过（见下面的用例）；
    # 无法识别的会议与过短的题目则要当场记为问题
    missing_scope = records[0]
    assert missing_scope.conference is None and missing_scope.year is None
    assert missing_scope.problems == []

    too_short = records[1]
    assert any("过短" in problem for problem in too_short.problems)

    unknown_venue = records[2]
    assert any("会议" in problem for problem in unknown_venue.problems)


def test_import_records_reuses_dedup_and_keywords(temp_db: Path):
    """适配器导入复用统一逻辑：去重生效，关键词被处理。"""
    session_scope = _session_scope()
    records = [
        adapters.DatasetRecord(
            title="Object Detection with Transformer Detectors",
            conference="CVPR",
            year=2024,
            abstract="We study object detection with transformer detectors.",
            keywords=["检测"],
            source="dataset",
            source_id="D-1",
        )
    ]

    with session_scope() as session:
        result = adapters.import_records(session, records)
        assert result.created == 1
        assert result.skipped == 0

    with session_scope() as session:
        # 同样的记录再来一次：应走更新而不是新建
        again = adapters.import_records(session, [records[0]])
        assert again.created == 0
        assert again.updated == 1

    with session_scope() as session:
        rows = session.exec(__import__("sqlmodel").select(__import__(
            "app.models.entities", fromlist=["Paper"]).Paper)).all()
        assert len(rows) == 1
        paper = rows[0]
        assert paper.keyword_status == "done"
        assert paper.primary_source == "dataset"


def test_import_records_uses_same_validation_as_manual_create(temp_db: Path):
    """题目过短等校验与手工新增一致：由统一的保存逻辑拒绝。"""
    session_scope = _session_scope()
    bad = adapters.DatasetRecord(
        title="Short", conference="CVPR", year=2024, source="dataset", source_id="D-2"
    )
    with session_scope() as session:
        result = adapters.import_records(session, [bad], process_keywords=False)
        assert result.created == 0
        assert result.skipped == 1
        assert "过短" in result.failures[0][1], result.failures


def test_adapter_and_manual_create_share_dedup_key(temp_db: Path):
    """同一条论文经适配器与手工新增进来，去重键一致，只留一条记录。"""
    session_scope = _session_scope()
    title = "A Shared Title For Dedup Check"
    with session_scope() as session:
        save_paper(session, title=title, conference="CVPR", year=2024, abstract="A.")
    with session_scope() as session:
        result = adapters.import_records(
            session,
            [adapters.DatasetRecord(title=title, conference="CVPR", year=2024)],
            process_keywords=False,
        )
        # 命中已有记录 → 记为更新，不新建
        assert result.created == 0
        assert result.updated == 1
    with session_scope() as session:
        from sqlmodel import func, select

        from app.models.entities import Paper

        assert session.exec(select(func.count()).select_from(Paper)).one() == 1


def _session_scope():
    from app.db.engine import session_scope

    return session_scope
