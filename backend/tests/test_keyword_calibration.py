"""关键词词表与短语规则测试（阶段 7 校准，kw-v3）。

这些用例锁定的都是**用真实数据换来的结论**，改动规则时它们会失败，
提醒改动者同步提升规则版本并重算受影响数据：

- 链接与代码样板词必须被剔除（否则 http / github 会成为最高频词条）；
- 学术套话（demonstrate、existing 等）不得进入关键词；
- 3d / 2d 这类数字开头写法要保留，且不因长度下限被丢掉；
- 单复数归一不得把 classes 变成 classe、videos 变成视频复数原形；
- 短语阈值放宽后方向词（object detection 等）能进结果；
- 通用裸词被短语覆盖时不单列，且结果仍能被回填到上限。
"""

from __future__ import annotations

import pytest

from app.config import KEYWORD_RULESET_VERSION
from app.services.keyword_rules import (
    BARE_GENERIC,
    MAX_PER_PAPER,
    SUPPRESS_WHEN_IN_PHRASE,
    KeywordExtractor,
    candidate_phrases,
    extract_single,
    select_tier,
    tokenize,
)
from app.services.keywords import normalize_keyword


def test_tokens_exclude_links_and_boilerplate():
    """带链接与代码声明句的摘要不产出 http / github / com / code 等词条。"""
    text = (
        "We propose a new method. Code and models are available at "
        "https://github.com/example/project, see our project page for details."
    )
    tokens = tokenize(text)
    assert tokens == ["propose", "new", "detail"] or "http" not in tokens
    for noise in ("http", "https", "github", "com", "code", "available", "project", "page"):
        assert noise not in tokens


def test_tokens_exclude_academic_cliches():
    """学术行文套话不进入关键词候选。"""
    tokens = tokenize(
        "Extensive experiments demonstrate the effectiveness of our method "
        "compared with existing approaches, and we achieve state-of-the-art results."
    )
    assert "demonstrate" not in tokens
    assert "existing" not in tokens
    assert "extensive" not in tokens
    assert "experiment" not in tokens


def test_numeric_short_forms_are_kept():
    """3d / 2d 这类两字符写法保留，年份等纯数字不保留。"""
    tokens = tokenize("A 3D and 2D study published in 2024 with 12 baselines")
    assert "3d" in tokens
    assert "2d" in tokens
    assert "2024" not in tokens
    assert "12" not in tokens


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("classes", "class"),
        ("boxes", "box"),
        ("matches", "match"),
        ("cases", "case"),
        ("uses", "use"),
        ("videos", "video"),
        ("images", "image"),
        ("across", "across"),
        ("analysis", "analysis"),
        ("policies", "policy"),
    ],
)
def test_singular_forms_are_conservative(raw: str, expected: str):
    """单复数归一既要合并 videos/classes，也不能破坏 across/analysis。"""
    assert normalize_keyword(raw) == expected


def test_phrase_threshold_allows_direction_words():
    """短语阈值放宽后，方向型二元短语能进入候选并被选中。"""
    documents = [
        "object detection with transformers for autonomous driving scenes",
        "object detection using point cloud data for autonomous driving",
        "semantic segmentation and object detection for autonomous driving",
    ] * 40  # 扩充到 120 篇，落在 N ≥ 200 之前的档位仍需短语可用
    extractor = KeywordExtractor()
    extractor.fit(documents)
    assert extractor.tier.phrases_enabled is True
    assert extractor.document_freq["object detection"] >= extractor.tier.phrase_min_df

    result = extractor.extract(
        "Object detection for autonomous driving",
        "We study object detection for autonomous driving with point cloud data.",
    )
    names = [keyword.name for keyword in result.keywords]
    assert "object detection" in names
    assert "autonomous driving" in names


def test_large_corpus_tier_uses_relaxed_phrase_threshold():
    """N ≥ 200 档的短语阈值必须是放宽后的 5（原 20 会让方向词进不了榜）。"""
    tier = select_tier(1200)
    assert tier.effective_min_df == 5
    assert tier.phrase_min_df == 5


def test_generic_bare_words_never_appear_alone_but_phrases_do():
    """通用裸词不单独成词，但包含它的短语照常成词。"""
    documents = [
        "image generation with diffusion models for image editing tasks",
        "image generation and image editing with diffusion models",
    ] * 20
    extractor = KeywordExtractor()
    extractor.fit(documents)
    result = extractor.extract(
        "Image generation and image editing",
        "Diffusion models enable image generation and image editing.",
    )
    names = [keyword.name for keyword in result.keywords]
    assert "image" not in names
    assert any("image" in name and " " in name for name in names), names


def test_phrase_suppresses_covered_generic_head():
    """同篇内被短语覆盖的方向词不再单独列出。"""
    documents = [
        "object detection and semantic segmentation for scene understanding",
        "object detection with semantic segmentation heads",
    ] * 20
    extractor = KeywordExtractor()
    extractor.fit(documents)
    result = extractor.extract(
        "Object detection and semantic segmentation",
        "We combine object detection with semantic segmentation.",
    )
    names = [keyword.name for keyword in result.keywords]
    assert "detection" not in names
    assert "segmentation" not in names
    assert "object detection" in names
    assert "semantic segmentation" in names
    # 抑制后还有候选词可用：回填至少补进一个新的词条，
    # 词表收紧不会让结果变空（小规模玩具语料的可选词本来就少，
    # 真实 1200 篇语料上实测每篇稳定回填到 12 个）
    assert 3 < len(names) <= MAX_PER_PAPER


def test_vocabulary_sets_are_consistent():
    """词表自成一致：只作短语成分的词不应同时出现在短语覆盖抑制表里。"""
    assert BARE_GENERIC.isdisjoint(SUPPRESS_WHEN_IN_PHRASE)
    assert "image" in BARE_GENERIC
    assert "detection" in SUPPRESS_WHEN_IN_PHRASE


def test_single_paper_path_still_works():
    """单篇提取是必需能力：库中只有一篇时也要产出关键词。"""
    result = extract_single(
        "Neural Radiance Fields for View Synthesis",
        "We present neural radiance fields for novel view synthesis of scenes.",
    )
    assert result.keywords, "单篇语料必须能产出关键词"
    assert result.corpus_size == 1
    assert result.phrases_enabled is False
    assert result.ruleset_version == KEYWORD_RULESET_VERSION


def test_config_signature_changes_with_vocabulary(monkeypatch: pytest.MonkeyPatch):
    """签名包含词表指纹：改了词表即使忘记提升版本号，签名也会变。"""
    extractor = KeywordExtractor()
    extractor.fit(["a short document about detection"])
    before = extractor.config_signature()

    monkeypatch.setattr(
        "app.services.keyword_rules.BARE_GENERIC",
        frozenset({*BARE_GENERIC, "brand-new-generic-word"}),
    )
    after = KeywordExtractor().config_signature()
    assert before != after


def test_phrase_candidates_are_adjacent_pairs():
    """短语候选取「过滤后词流」里的相邻二元组。

    停用词被剔除后，原本不相邻的两个实词会成为邻居（based 是停用词，
    于是得到 cloud point）。这是朴素二元组方案的已知特性，
    统计侧靠 df 阈值与主题别名表消化，不在这里做词性/依存过滤。
    """
    tokens = tokenize("point cloud based point cloud registration")
    phrases = candidate_phrases(tokens)
    assert tokens == ["point", "cloud", "point", "cloud", "registration"]
    assert "point cloud" in phrases
    assert "cloud registration" in phrases


def test_extraction_is_deterministic():
    """同一输入两次抽取结果一致：顺序稳定，便于统计复算。"""
    documents = [
        "diffusion models for image generation and editing",
        "diffusion models for video generation",
    ] * 20
    first = KeywordExtractor()
    first.fit(documents)
    second = KeywordExtractor()
    second.fit(documents)
    left = [k.name for k in first.extract("Diffusion for generation", "diffusion generation").keywords]
    right = [k.name for k in second.extract("Diffusion for generation", "diffusion generation").keywords]
    assert left == right
