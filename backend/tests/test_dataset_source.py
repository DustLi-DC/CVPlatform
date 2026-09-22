"""完整论文集来源（HuggingFace 数据集）与数据性质的测试。

外部响应全部用固定样例替身，不访问网络；数据性质（完整论文集 / 试跑截断 / 抽样）的判定
用独立临时数据库验证。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import KEYWORD_RULESET_VERSION
from app.db.engine import session_scope
from app.services import stats
from app.services.sources import huggingface as hf
from tests.helpers import insert_paper

INFO_PAYLOAD = {
    "dataset_info": {
        "default": {
            "splits": {"train": {"num_examples": 2716}},
            "features": {
                "paper_id": {"dtype": "string"},
                "title": {"dtype": "string"},
                "abstract": {"dtype": "large_string"},
            },
        }
    }
}
ROW = {
    "paper_id": "Zeng_Unmixing_Diffusion",
    "title": "Unmixing Diffusion for Denoising",
    "abstract": "An abstract.",
    "authors": ["First Author", "Second Author"],
    "cvf_url": "https://openaccess.thecvf.com/content/CVPR2024/html/x.html",
    "pdf_url": "https://openaccess.thecvf.com/content/CVPR2024/papers/x.pdf",
}


def test_parse_info_payload():
    ref = hf._as_dataset_ref(INFO_PAYLOAD, "CVPR", 2024)
    assert ref is not None
    assert ref.dataset == "ai-conferences/CVPR2024"
    assert ref.rows == 2716
    assert ref.url.endswith("ai-conferences/CVPR2024")


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"dataset_info": {}},
        {"dataset_info": {"default": {"splits": {}}}},
        {"dataset_info": {"default": {"splits": {"train": {}}, "features": {"title": {}}}}},
        # 缺少 title 字段说明不是论文数据集
        {
            "dataset_info": {
                "default": {
                    "splits": {"train": {"num_examples": 10}},
                    "features": {"paper_id": {"dtype": "string"}},
                }
            }
        },
    ],
)
def test_parse_info_payload_rejects_unexpected_shapes(payload):
    assert hf._as_dataset_ref(payload, "CVPR", 2024) is None


def test_normalize_maps_fields_and_marks_source():
    ref = hf.DatasetRef("ai-conferences/CVPR2024", "CVPR", 2024, 2716)
    record = hf._normalize(ROW, ref)
    assert record["title"] == ROW["title"]
    assert record["landing_url"] == ROW["cvf_url"]
    assert record["pdf_url"] == ROW["pdf_url"]
    assert record["conference"] == "CVPR"
    assert record["year"] == 2024
    assert record["source"] == "huggingface"
    # 来源标识写明「哪个数据集 + 数据集内 id」，便于逐条回溯
    assert record["source_id"] == "ai-conferences/CVPR2024#Zeng_Unmixing_Diffusion"
    assert record["authors"] == ["First Author", "Second Author"]


def test_normalize_falls_back_to_ecva_url_and_tolerates_bad_authors():
    ref = hf.DatasetRef("ai-conferences/ECCV2022", "ECCV", 2022, 1645)
    row = {
        "paper_id": "123",
        "title": "A Title",
        "ecva_url": "https://www.ecva.net/papers/123.html",
        "authors": "not-a-list",
        "abstract": "",
    }
    record = hf._normalize(row, ref)
    assert record["landing_url"] == "https://www.ecva.net/papers/eccv_2022/123.html".replace(
        "eccv_2022/", "papers/eccv_2022/"
    ) or record["landing_url"] == "https://www.ecva.net/papers/123.html"
    assert record["authors"] == []
    assert record["abstract"] is None


def test_iter_records_pages_json_when_parquet_unavailable(monkeypatch):
    """没有 pyarrow 时回落到 JSON 分页，且能翻页到结束（不受单页上限影响）。"""
    ref = hf.DatasetRef("ai-conferences/CVPR2024", "CVPR", 2024, 250)
    pages = {
        0: ([dict(ROW, paper_id=f"p{index}", title=f"Title {index}") for index in range(100)], 250),
        100: ([dict(ROW, paper_id=f"p{index}", title=f"Title {index}") for index in range(100, 200)], 250),
        200: ([dict(ROW, paper_id=f"p{index}", title=f"Title {index}") for index in range(200, 250)], 250),
    }

    monkeypatch.setattr(hf, "parquet_available", lambda: False)
    monkeypatch.setattr(hf, "fetch_page", lambda ref, offset, **kwargs: pages[offset])

    records = list(hf.iter_records(ref))
    assert len(records) == 250
    assert records[0]["title"] == "Title 0"
    assert records[-1]["title"] == "Title 249"


def test_iter_records_respects_limit(monkeypatch):
    ref = hf.DatasetRef("ai-conferences/CVPR2024", "CVPR", 2024, 250)
    monkeypatch.setattr(hf, "parquet_available", lambda: False)
    monkeypatch.setattr(
        hf,
        "fetch_page",
        lambda ref, offset, length=100, **kwargs: (
            [dict(ROW, paper_id=f"p{index}") for index in range(offset, offset + length)],
            250,
        ),
    )
    assert len(list(hf.iter_records(ref, limit=30))) == 30


def test_discover_skips_incomplete_datasets(monkeypatch):
    """摘要覆盖率不达标的年份必须跳过并给出原因（会议数据仍在补齐）。"""
    refs = {
        ("CVPR", 2024): hf.DatasetRef("ai-conferences/CVPR2024", "CVPR", 2024, 2716),
        ("ECCV", 2026): hf.DatasetRef("ai-conferences/ECCV2026", "ECCV", 2026, 2864),
    }
    monkeypatch.setattr(hf, "probe", lambda conference, year, **kwargs: refs.get((conference, year)))
    monkeypatch.setattr(
        hf,
        "abstract_ratio",
        lambda ref, **kwargs: 0.99 if ref.year == 2024 else 0.71,
    )
    notes: list[str] = []
    found = hf.discover(
        conferences=("CVPR", "ECCV"), min_year=2024, max_year=2026, on_note=notes.append
    )
    assert [ref.dataset for ref in found] == ["ai-conferences/CVPR2024"]
    assert any("跳过" in note and "71%" in note for note in notes)


def test_dataset_import_marks_coverage_kind(temp_db: Path, monkeypatch):
    """导入完整论文集后，该会议年份应被标为 full，且记录数据集修订号。"""
    ref = hf.DatasetRef("ai-conferences/CVPR2024", "CVPR", 2024, 2, revision="abc123")

    def fake_iter(ref, *, limit=None, timeout=None, on_progress=None):
        for index in range(2):
            yield hf._normalize(dict(ROW, paper_id=f"p{index}", title=f"HFDataset Paper {index}"), ref)

    monkeypatch.setattr(hf, "iter_records", fake_iter)
    monkeypatch.setattr(hf, "fetch_revision", lambda dataset, **kwargs: "abc123")

    from app.services import dataset_import

    with session_scope() as session:
        summary = dataset_import.import_dataset(session, ref)
    assert summary.created == 2
    assert summary.revision == "abc123"

    with session_scope() as session:
        detail = stats.coverage_detail(session)
    cell = next(
        item
        for item in detail["covered"]
        if item["conference"] == "CVPR" and item["year"] == 2024
    )
    assert cell["coverage_kind"] == "full"
    assert detail["coverage_kinds"]["full"] == 1
    assert detail["sampled"] is False
    assert detail["full_coverage_years"] == [{"conference": "CVPR", "year": 2024}]
    assert detail["datasets"][0]["dataset"] == "ai-conferences/CVPR2024"
    assert detail["datasets"][0]["revision"] == "abc123"


def test_limited_import_is_marked_partial_not_full(temp_db: Path, monkeypatch):
    """试跑截断（--limit）不能算作完整论文集。"""
    ref = hf.DatasetRef("ai-conferences/CVPR2024", "CVPR", 2024, 2716)

    def fake_iter(ref, *, limit=None, timeout=None, on_progress=None):
        yield hf._normalize(dict(ROW, paper_id="p0", title="Partial Import Paper"), ref)

    monkeypatch.setattr(hf, "iter_records", fake_iter)
    monkeypatch.setattr(hf, "fetch_revision", lambda dataset, **kwargs: None)

    from app.services import dataset_import

    with session_scope() as session:
        dataset_import.import_dataset(session, ref, limit=1)
    with session_scope() as session:
        detail = stats.coverage_detail(session)
    cell = detail["covered"][0]
    assert cell["coverage_kind"] == "partial"
    assert detail["coverage_kinds"] == {
        "full": 0,
        "partial": 1,
        "sampled": 0,
        "unknown": 0,
    }
    assert detail["sampled"] is False


def test_sampled_cell_kind_without_dataset_record(temp_db: Path):
    """没有数据集记录的抽样目标组合标为 sampled，范围外的标为 unknown。"""
    insert_paper(
        temp_db,
        code="CVPR-2024-0001",
        title="Sampled Target Paper For Coverage",
        keyword_status="done",
        keyword_ruleset_version=KEYWORD_RULESET_VERSION,
    )
    insert_paper(
        temp_db,
        code="CVPR-2019-0001",
        title="Out Of Target Range Paper",
        year=2019,
        keyword_status="done",
        keyword_ruleset_version=KEYWORD_RULESET_VERSION,
    )
    with session_scope() as session:
        detail = stats.coverage_detail(session)
    kinds = {(cell["conference"], cell["year"]): cell["coverage_kind"] for cell in detail["covered"]}
    assert kinds[("CVPR", 2024)] == "sampled"
    assert kinds[("CVPR", 2019)] == "unknown"
    assert detail["coverage_kinds"]["sampled"] == 1
    assert detail["coverage_kinds"]["unknown"] == 1
    # 有抽样单元时整体标记为抽样（用于兼容旧文案），但逐单元性质仍然可查
    assert detail["sampled"] is True
