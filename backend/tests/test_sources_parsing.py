"""用固定响应样例验证解析、候选匹配与失败分支（阶段 5 任务第 8 条）。

这些样例是**真实响应的截取**（2026-09 从 CVF、ECVA、OpenAlex 取得后裁短），
不依赖网络即可回归，因此解析逻辑变化会被立刻发现。
联网端到端验证另行进行，见阶段交付说明。
"""

from __future__ import annotations

import pytest

from app.services.sources import cvf, ecva, openalex
from app.services.sources.http import SourceTimeout, SourceUnavailable

# ---------------------------------------------------------------- CVF 样例

CVF_INDEX_SAMPLE = """
<html><body><dl>
<dt class="ptitle"><br><a href="/content/CVPR2024/html/Zeng_Unmixing_Diffusion_CVPR_2024_paper.html">
   Unmixing   Diffusion for Self-Supervised Hyperspectral Image Denoising</a></dt>
<dd>Haijin Zeng, Jiezhang Cao</dd>
<dt class="ptitle"><br><a href="/content/CVPR2024/html/Chen_InternVL_CVPR_2024_paper.html">
   InternVL: Scaling up Vision Foundation Models and Aligning for Generic
   Visual-Linguistic Tasks</a></dt>
<dd>Zhe Chen, Weiyun Wang</dd>
</dl></body></html>
"""

CVF_PAPER_SAMPLE = """
<html><body>
<div id="papertitle">Unmixing Diffusion for Self-Supervised Hyperspectral Image Denoising</div>
<div id="authors"><a href="#">Haijin Zeng</a>, <a href="#">Jiezhang Cao</a>, Kai Zhang</div>
<div id="abstract">Hyperspectral images (HSIs) have extensive applications.
  Nevertheless, acquiring high signal-to-noise ratio HSI data remains a challenge.</div>
<div><a href="/content/CVPR2024/papers/Zeng_Unmixing_Diffusion_CVPR_2024_paper.pdf">pdf</a></div>
</body></html>
"""

CVF_PAPER_WITHOUT_ABSTRACT = """
<html><body>
<div id="papertitle">A Paper Without Abstract</div>
<div id="authors">First Author, Second Author</div>
</body></html>
"""


def test_cvf_parse_index_extracts_title_and_path():
    entries = cvf.parse_index(CVF_INDEX_SAMPLE)
    assert len(entries) == 2
    assert entries[0].title == (
        "Unmixing Diffusion for Self-Supervised Hyperspectral Image Denoising"
    )
    assert entries[0].paper_path == (
        "/content/CVPR2024/html/Zeng_Unmixing_Diffusion_CVPR_2024_paper.html"
    )
    # 标题里的换行会被折叠成单空格，副标题与连字符保留
    assert "Visual-Linguistic Tasks" in entries[1].title
    assert entries[0].landing_url.startswith("https://openaccess.thecvf.com/content/")


def test_cvf_parse_paper_extracts_all_fields():
    fields = cvf.parse_paper(
        CVF_PAPER_SAMPLE, paper_path="/content/CVPR2024/html/x_paper.html"
    )
    assert fields.title == (
        "Unmixing Diffusion for Self-Supervised Hyperspectral Image Denoising"
    )
    assert fields.authors == ["Haijin Zeng", "Jiezhang Cao", "Kai Zhang"]
    assert fields.abstract is not None and "Hyperspectral images" in fields.abstract
    assert fields.pdf_url is not None and fields.pdf_url.endswith(".pdf")
    assert fields.landing_url == (
        "https://openaccess.thecvf.com/content/CVPR2024/html/x_paper.html"
    )


def test_cvf_parse_paper_missing_fields_are_none():
    """缺失字段必须是 None，不能填占位文本。"""
    fields = cvf.parse_paper(CVF_PAPER_WITHOUT_ABSTRACT)
    assert fields.title == "A Paper Without Abstract"
    assert fields.abstract is None
    assert fields.pdf_url is None
    assert fields.authors == ["First Author", "Second Author"]


# ---------------------------------------------------------------- ECVA 样例

ECVA_INDEX_SAMPLE = """
<h2>ECCV Conference Papers</h2>
<button class="accordion">ECCV 2024 Papers</button>
<div class="accordion-content"><dl>
<dt class="ptitle"><br>
<a href=papers/eccv_2024/papers_ECCV/html/4_ECCV_2024_paper.php> Is Retain Set All You Need
in Machine Unlearning?</a></dt><dd> Jacopo Bonato*, Marco Cotogni</dd>
<dd>[<a href='papers/eccv_2024/papers_ECCV/papers/00004.pdf'>pdf</a>]
  [<a href='papers/eccv_2024/papers_ECCV/papers/00004-supp.pdf'>supplementary material</a>]</dd>
</dl></div>
<button class="accordion">ECCV 2022 Papers</button>
<div class="accordion-content"><dl>
<dt class="ptitle"><br>
<a href=papers/eccv_2022/papers_ECCV/html/9_ECCV_2022_paper.php>An Older Paper Title</a></dt>
<dd>Someone</dd>
</dl></div>
"""

ECVA_PAPER_SAMPLE = """
<html><body>
<div id="papertitle">Is Retain Set All You Need in Machine Unlearning?</div>
<div id="authors">Jacopo Bonato, Marco Cotogni</div>
<div id="abstract">In this paper, we introduce Selective-distillation for Class and
  Architecture-agnostic unleaRning (SCAR), a novel approximate unlearning method.</div>
<dd>[<a href='papers/eccv_2024/papers_ECCV/papers/00004.pdf'>pdf</a>]
    [<a href='papers/eccv_2024/papers_ECCV/papers/00004-supp.pdf'>supplementary material</a>]</dd>
</body></html>
"""


def test_ecva_parse_index_handles_unquoted_hrefs_and_sections():
    """ECVA 的 href 没有引号，且多年份同页，必须按年份分段且不漏条目。"""
    entries_2024 = ecva.parse_index(ECVA_INDEX_SAMPLE, year=2024)
    assert len(entries_2024) == 1
    assert entries_2024[0].year == 2024
    assert entries_2024[0].paper_path == (
        "papers/eccv_2024/papers_ECCV/html/4_ECCV_2024_paper.php"
    )
    assert "Machine Unlearning" in entries_2024[0].title

    entries_2022 = ecva.parse_index(ECVA_INDEX_SAMPLE, year=2022)
    assert [item.title for item in entries_2022] == ["An Older Paper Title"]

    # 不指定年份时返回全部
    assert len(ecva.parse_index(ECVA_INDEX_SAMPLE)) == 2


def test_ecva_parse_paper_prefers_main_pdf_over_supplementary():
    fields = ecva.parse_paper(
        ECVA_PAPER_SAMPLE,
        paper_path="papers/eccv_2024/papers_ECCV/html/4_ECCV_2024_paper.php",
    )
    assert fields.title == "Is Retain Set All You Need in Machine Unlearning?"
    assert fields.abstract is not None and "SCAR" in fields.abstract
    # 正文 PDF，不能取到 supplementary
    assert fields.pdf_url is not None
    assert fields.pdf_url.endswith("00004.pdf")
    assert "supp" not in fields.pdf_url


# ------------------------------------------------------------ OpenAlex 样例

OPENALEX_SEARCH_SAMPLE = {
    "meta": {"count": 2},
    "results": [
        {
            "id": "https://openalex.org/W4401896001",
            "title": "Sapiens: Foundation for Human Vision Models",
            "publication_year": 2024,
            "type": "conference-paper",
            "doi": "https://doi.org/10.1007/978-3-031-73235-5_12",
            "primary_location": {
                "landing_page_url": "https://doi.org/10.1007/978-3-031-73235-5_12",
                "source": {"display_name": "Lecture Notes in Computer Science"},
            },
            "best_oa_location": None,
            "abstract_inverted_index": None,
            "authorships": [{"author": {"display_name": "Rawal Rakhimov"}}],
        },
        {
            "id": "https://openalex.org/W4402633288",
            "title": "Sapiens: Foundation for Human Vision Models",
            "publication_year": 2024,
            "type": "preprint",
            "doi": "https://doi.org/10.48550/arxiv.2408.12569",
            "primary_location": {
                "landing_page_url": "http://arxiv.org/abs/2408.12569",
                "source": {"display_name": "arXiv (Cornell University)"},
            },
            "best_oa_location": {"pdf_url": "https://arxiv.org/pdf/2408.12569"},
            "abstract_inverted_index": {
                "We": [0],
                "present": [1],
                "Sapiens": [2],
                "foundation": [3],
                "models": [4],
            },
            "authorships": [
                {"author": {"display_name": "Rawal Rakhimov"}},
                {"author": {"display_name": "Timur Mamedov"}},
            ],
        },
        {
            "id": "https://openalex.org/W9999",
            "title": "DETRs Beat YOLOs on Real-time Object Detection",
            "publication_year": 2024,
            "type": "conference-paper",
            "doi": "https://doi.org/10.1109/cvpr52733.2024.01605",
            "primary_location": {
                "landing_page_url": "https://doi.org/10.1109/cvpr52733.2024.01605",
                "source": {"display_name": None},
            },
            "abstract_inverted_index": {"Real": [0], "time": [1], "detection": [2]},
            "authorships": [],
        },
    ],
}


def test_openalex_restore_abstract_from_inverted_index():
    assert openalex.restore_abstract({"a": [1], "b": [0]}) == "b a"
    assert openalex.restore_abstract({"a": [0, 2], "b": [1]}) == "a b a"
    assert openalex.restore_abstract(None) is None
    assert openalex.restore_abstract({}) is None
    # 结构异常时返回 None 而不是抛错
    assert openalex.restore_abstract({"a": "not-a-list"}) is None


def test_openalex_infer_conference_never_guesses():
    assert (
        openalex.infer_conference("https://doi.org/10.1109/cvpr52733.2024.01605", None)
        == "CVPR"
    )
    assert (
        openalex.infer_conference("https://doi.org/10.1109/iccv51070.2023.00371", None)
        == "ICCV"
    )
    # ECCV 的 DOI 指向 Springer，推不出来就必须返回 None
    assert (
        openalex.infer_conference("https://doi.org/10.1007/978-3-031-73235-5_12", None)
        is None
    )
    assert (
        openalex.infer_conference(None, "European Conference on Computer Vision")
        == "ECCV"
    )


def test_openalex_parse_search_marks_preprint_and_missing_abstract():
    candidates = openalex.parse_search(OPENALEX_SEARCH_SAMPLE)
    assert len(candidates) == 3

    conference_version = candidates[0]
    assert conference_version.year == 2024
    assert conference_version.abstract is None
    assert any("没有提供摘要" in note for note in conference_version.notes)
    # 会议版没有摘要也没有 PDF，但落地页来自 DOI
    assert conference_version.landing_url is not None
    assert conference_version.pdf_url is None

    preprint = candidates[1]
    assert preprint.abstract == "We present Sapiens foundation models"
    assert preprint.pdf_url == "https://arxiv.org/pdf/2408.12569"
    assert any("预印本" in note for note in preprint.notes)
    assert preprint.conference is None

    cvpr_paper = candidates[2]
    assert cvpr_paper.conference == "CVPR"  # 从 DOI 识别
    assert cvpr_paper.authors == []


def test_openalex_parse_search_tolerates_bad_payload():
    assert openalex.parse_search(None) == []
    assert openalex.parse_search({"results": "not-a-list"}) == []
    assert openalex.parse_search({"results": [None, 1, "x"]}) == []


def test_token_set_similarity_ranks_related_titles_higher():
    target = "Sapiens: Foundation for Human Vision Models"
    identical = openalex.token_set_similarity(target, target)
    near = openalex.token_set_similarity(target, "Sapiens Foundation for Human Vision")
    unrelated = openalex.token_set_similarity(
        target, "Psychology of Bounded Rationality"
    )
    assert identical == 1.0
    assert 0.7 < near < 1.0
    assert unrelated < 0.2
    # 连字符与标点不影响比较
    assert openalex.token_set_similarity(
        "Self-Supervised Learning", "self supervised learning"
    ) == 1.0


# --------------------------------------------------------- 来源失败分支

def test_source_errors_are_distinct_types():
    """超时与不可用必须是两类错误，接口层据此返回 504 与 502。"""
    assert issubclass(SourceTimeout, Exception)
    assert issubclass(SourceUnavailable, Exception)
    timeout = SourceTimeout("cvf", "cvf 请求超时（10 秒）")
    unavailable = SourceUnavailable("cvf", "cvf 返回 HTTP 503", 503)
    assert timeout.source == "cvf"
    assert unavailable.status == 503
    # 两者不能互相替代
    assert not isinstance(timeout, SourceUnavailable)
    assert not isinstance(unavailable, SourceTimeout)


@pytest.mark.parametrize("module", [cvf, ecva, openalex])
def test_sources_are_addressable(module):
    """每个来源都必须暴露来源名，用于记录与错误提示。"""
    assert module.SOURCE_NAME in {"cvf", "ecva", "openalex"}
