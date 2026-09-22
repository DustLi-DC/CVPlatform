"""关键词抽取与规范化模块的验证（阶段 5 任务第 5、6 条）。

重点覆盖：
- 单篇（语料只有一篇，含「只有标题」）必须能产出关键词——这是阶段 5 的验收样例；
- 语料规模分档，避免固定 MIN_DF 把小语料的候选词全部滤掉；
- 停用词与学术套话被过滤；
- 短语（如 object detection）在多篇语料下被保留；
- 「抽取成功但为空」与「处理失败」是两种状态。
"""

from __future__ import annotations

from app.services.keyword_rules import (
    MAX_PER_PAPER,
    KeywordExtractor,
    extract_single,
    select_tier,
    tokenize,
)

TITLE = "DETRs Beat YOLOs on Real-time Object Detection"
ABSTRACT = (
    "We propose a real-time end-to-end object detection transformer. "
    "The detector removes the need for non-maximum suppression and achieves "
    "strong results on object detection benchmarks."
)


def test_single_document_title_only_produces_keywords():
    """语料只有一篇且没有摘要时也必须产出关键词——不能因 min_df 而归零。"""
    result = extract_single("Self-Supervised Learning for Vision Representation", None)
    assert not result.is_empty
    assert result.corpus_size == 1
    assert result.effective_min_df == 1
    names = [keyword.name for keyword in result.keywords]
    assert "learning" in names
    assert "self-supervised" in names


def test_single_document_with_abstract_produces_keywords():
    result = extract_single(TITLE, ABSTRACT)
    assert not result.is_empty
    names = [keyword.name for keyword in result.keywords]
    assert "detection" in names
    # 停用词与套话不得出现
    for stopword in ("the", "we", "and", "for", "propose", "results"):
        assert stopword not in names


def test_keywords_are_capped_and_ranked():
    extractor = KeywordExtractor()
    extractor.fit([f"{TITLE} {ABSTRACT}" for _ in range(5)])
    result = extractor.extract(TITLE, ABSTRACT)
    assert 0 < len(result.keywords) <= MAX_PER_PAPER
    # rank 从 0 开始且连续
    assert [keyword.rank for keyword in result.keywords] == list(
        range(len(result.keywords))
    )


def test_tier_ladder_matches_design():
    assert select_tier(1).effective_min_df == 1
    assert select_tier(29).effective_min_df == 1
    assert select_tier(30).effective_min_df == 2
    assert select_tier(199).effective_min_df == 2
    assert select_tier(200).effective_min_df == 5
    # 短语在小语料下关闭，避免互信息估计不可靠
    assert select_tier(10).phrases_enabled is False
    assert select_tier(200).phrases_enabled is True


def test_phrases_are_kept_when_corpus_supports_them():
    documents = [
        f"Object detection with transformers for {index} scenario"
        for index in range(40)
    ]
    extractor = KeywordExtractor()
    extractor.fit(documents)
    result = extractor.extract("Object detection with transformers", None)
    names = [keyword.name for keyword in result.keywords]
    assert any(" " in name for name in names), f"未保留短语：{names}"


def test_stopwords_and_boilerplate_are_filtered():
    tokens = tokenize(
        "In this paper we propose a novel method. Our approach achieves "
        "state-of-the-art performance on the dataset."
    )
    for stopword in (
        "the",
        "in",
        "we",
        "our",
        "paper",
        "method",
        "approach",
        "propose",
        "novel",
        "state",
        "art",
        "performance",
        "dataset",
        "achieves",
    ):
        assert stopword not in tokens, f"{stopword} 不应作为候选词"
    assert "performance" not in tokens


def test_normalization_is_reused_from_keyword_service():
    """词形归一复用 services.keywords.normalize_keyword，避免两处实现漂移。"""
    from app.services.keywords import normalize_keyword

    assert normalize_keyword("Object Detection") == "object detection"
    result = extract_single("Object Detection Networks", None)
    for keyword in result.keywords:
        assert keyword.normalized == normalize_keyword(keyword.name)


def test_empty_result_is_success_not_failure():
    """抽取成功但没有关键词时，结果是空的，但仍是一次成功处理。"""
    extractor = KeywordExtractor()
    extractor.fit(["the and of for"])
    result = extractor.extract("the and of for")
    assert result.is_empty
    assert result.corpus_size == 1


def test_config_signature_changes_with_parameters():
    small = KeywordExtractor()
    small.fit(["a b c"])
    large = KeywordExtractor()
    large.fit([f"paper number {index} about vision" for index in range(250)])
    assert small.config_signature() != large.config_signature()
    assert len(small.config_signature()) == 12


def test_missing_abstract_uses_title_only():
    """摘要缺失时只用标题：标题里的词保留，只存在于摘要里的词不得出现。"""
    title_only = extract_single(TITLE, None)
    with_abstract = extract_single(TITLE, ABSTRACT)

    title_words = {keyword.name for keyword in title_only.keywords}
    abstract_words = {keyword.name for keyword in with_abstract.keywords}

    assert title_words, "只有标题时也必须产出关键词"
    assert "detection" in title_words
    # 摘要里的词不应该凭空出现在只有标题的结果中
    abstract_only = abstract_words - title_words
    assert abstract_only, "摘要应当贡献额外关键词，否则该用例没有区分度"
    assert title_words.isdisjoint(
        {name for name in abstract_only if "suppression" in name}
    )
    assert not any("suppression" in name for name in title_words)
