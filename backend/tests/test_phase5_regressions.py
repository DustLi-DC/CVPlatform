"""阶段 5 联网验证中发现并修复的两个缺陷的回归用例。

1. 单复数归一过于激进：对整串做 `\\b(\\w{4,})s\\b` 替换会把 across 变成 acros、
   analysis 变成 analysi、class 变成 clas，而这些归一形式是 keyword 表的唯一键，
   会直接显示成错词。改为逐词、保守地处理。
2. ECVA 详情页的 PDF 链接是 `../../../../` 相对路径，且不以 papers/ 开头，
   原正则要求以 papers/ 开头，导致 ECCV 论文全部取不到原文链接。
"""

from __future__ import annotations

from app.services.keywords import normalize_keyword
from app.services.sources import ecva


def test_words_ending_in_s_are_not_corrupted():
    """以 ss/us/is/os/as 结尾的词不是复数，不能被去掉尾部 s。"""
    for word in (
        "across",
        "analysis",
        "loss",
        "class",
        "process",
        "gaussian",
        "status",
    ):
        assert normalize_keyword(word) == word, f"{word} 不应被改写"


def test_real_plurals_are_still_normalized():
    assert normalize_keyword("detections") == "detection"
    assert normalize_keyword("models") == "model"
    assert normalize_keyword("studies") == "study"
    assert normalize_keyword("benchmarks") == "benchmark"


def test_normalization_is_idempotent():
    """归一必须是幂等的：对已归一的词再跑一次结果不变，否则唯一键会漂移。"""
    for word in (
        "across",
        "detections",
        "studies",
        "self-supervised",
        "object detection",
    ):
        once = normalize_keyword(word)
        assert normalize_keyword(once) == once, word


def test_phrase_and_canonical_forms_unchanged():
    assert normalize_keyword("Object Detection") == "object detection"
    assert normalize_keyword("Self-Supervised Learning") == "self-supervised learning"
    assert normalize_keyword("3D Gaussian Splatting") == "3d gaussian splatting"


ECVA_RELATIVE_PDF_SAMPLE = """
<html><body>
<div id="papertitle">Sapiens: Foundation for Human Vision Models</div>
<div id="authors">Rawal Rakhimov, Timur Mamedov</div>
<div id="abstract">We present Sapiens, a family of foundation models for human vision.</div>
<dd>[<a href='../../../../papers/eccv_2024/papers_ECCV/papers/00529.pdf'>pdf</a>]
    [<a href='../../../../papers/eccv_2024/papers_ECCV/papers/00529-supp.pdf'>supplementary material</a>]</dd>
</body></html>
"""


def test_ecva_relative_pdf_is_resolved_against_paper_page():
    """相对路径（../../../../）必须按详情页地址解析成绝对链接。"""
    fields = ecva.parse_paper(
        ECVA_RELATIVE_PDF_SAMPLE,
        paper_path="papers/eccv_2024/papers_ECCV/html/529_ECCV_2024_paper.php",
    )
    assert fields.pdf_url == (
        "https://www.ecva.net/papers/eccv_2024/papers_ECCV/papers/00529.pdf"
    )
    assert fields.landing_url == (
        "https://www.ecva.net/papers/eccv_2024/papers_ECCV/html/529_ECCV_2024_paper.php"
    )
    # supplementary 附件不能被当成正文
    assert "supp" not in fields.pdf_url


def test_ecva_absolute_pdf_still_works():
    html = """
    <div id="papertitle">Another Paper</div>
    <div id="abstract">Abstract text.</div>
    <dd>[<a href='https://www.ecva.net/papers/eccv_2022/papers_ECCV/papers/00009.pdf'>pdf</a>]</dd>
    """
    fields = ecva.parse_paper(
        html, paper_path="papers/eccv_2022/papers_ECCV/html/9_x.php"
    )
    assert fields.pdf_url == (
        "https://www.ecva.net/papers/eccv_2022/papers_ECCV/papers/00009.pdf"
    )


def test_ecva_without_pdf_reports_none():
    """没有 PDF 时必须是 None，不能拼出一个假链接。"""
    html = '<div id="papertitle">No PDF Here</div><div id="abstract">Text.</div>'
    fields = ecva.parse_paper(
        html, paper_path="papers/eccv_2022/papers_ECCV/html/1_x.php"
    )
    assert fields.pdf_url is None
    assert fields.landing_url is not None
