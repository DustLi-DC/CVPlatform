"""关键词抽取与规范化模块（阶段 5 提供，阶段 6、7 复用）。

设计依据：开发设计与验收.md 第 5 章。要点：

- **两级规范化分开**：词形归一在这里（确定性、可逆语义，写入 keyword.name_normalized）；
  主题归并属于统计展示层（阶段 6/7），不改写原始关键词。词形归一复用
  services/keywords.normalize_keyword，避免两处实现漂移。
- **语料分档**：固定 MIN_DF=5 在只有一两篇论文时会把候选词全部滤掉，
  因此按语料规模自适应（见 TIERS）。**单篇提取是必需能力**，不是兜底：
  语料只有一篇时也要能产出关键词，阶段 5 以此为验收样例。
- **不引入向量化依赖**：TF-IDF 用「词频 + 文档频次」的稀疏字典实现，
  TextRank 在单篇的词共现图上迭代，不构造大规模稠密矩阵。
- **规则版本**：规则、停用词、阈值或归一逻辑变化时必须提升 KEYWORD_RULESET_VERSION，
  统计只认当前版本（见 v_analysis_keyword）。
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass, field

from ..config import KEYWORD_RULESET_VERSION
from .keywords import normalize_keyword

# 候选词：英文单词与「词-词」连写（如 self-supervised），长度下限 3
_TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z\-]{2,}")

# 英语功能词与学术套话：这些词在摘要里高频出现但不指示研究方向
STOPWORDS: frozenset[str] = frozenset(
    """
    the a an and or but if then than that this these those there here
    of in on at to for from by with without within into over under about
    is are was were be been being do does did done doing have has had having
    we our us you your they their them it its he she his her
    as not no nor so such can could may might must shall should will would
    which who whom whose what when where why how all any both each few more
    most other some only own same too very just also however therefore thus
    paper papers work works method methods approach approaches result results
    show shows shown propose proposes proposed present presents presented
    introduce introduces introduced new novel based using used use uses
    experiments experiment experimental evaluation evaluate evaluated
    performance state art state-of-the-art achieve achieves achieved
    significantly improve improves improved improvement compared compare
    however moreover furthermore additionally finally first second third
    widely well good better best large small high low different various
    given provide provides provided obtain obtains obtained make makes made
    can be able two three four five one many much several both each
    task tasks problem problems dataset datasets model models
    """.split()
)

# 分档参数：语料规模 → (最小文档频次, 短语最小文档频次, 是否启用短语)
TIERS: tuple[tuple[int, int, int, bool], ...] = (
    # (语料上限, effective_min_df, phrase_min_df, phrases_enabled)
    (30, 1, 0, False),
    (200, 2, 3, True),
    (10**9, 5, 20, True),
)

# 每篇论文保留的关键词上限，以及两条打分路径各自取前几个
MAX_PER_PAPER = 12
TOP_TFIDF = 8
TOP_TEXTRANK = 8
# TextRank 参数
TEXTRANK_WINDOW = 5
TEXTRANK_ITERATIONS = 20
TEXTRANK_DAMPING = 0.85


@dataclass(frozen=True)
class Tier:
    """当前语料规模对应的分档参数。"""

    effective_min_df: int
    phrase_min_df: int
    phrases_enabled: bool


def select_tier(corpus_size: int) -> Tier:
    """按语料规模选择分档参数。"""
    for upper, min_df, phrase_min_df, phrases_enabled in TIERS:
        if corpus_size < upper:
            return Tier(min_df, phrase_min_df, phrases_enabled)
    raise AssertionError("TIERS 必须覆盖所有语料规模")


@dataclass
class ExtractedKeyword:
    """一个抽取结果：词名、归一形式与两条路径的分数。"""

    name: str
    normalized: str
    tfidf_score: float | None = None
    textrank_score: float | None = None
    rank: int = 0


@dataclass
class ExtractionResult:
    """一篇文档的抽取结果，连同产生它的语料与参数信息。"""

    keywords: list[ExtractedKeyword] = field(default_factory=list)
    corpus_size: int = 0
    effective_min_df: int = 1
    phrases_enabled: bool = False
    ruleset_version: str = KEYWORD_RULESET_VERSION

    @property
    def is_empty(self) -> bool:
        """抽取成功但没有任何关键词——与「处理失败」是两回事。"""
        return not self.keywords


def tokenize(text: str) -> list[str]:
    """分词：只保留长度 ≥ 3 的英文词与连写词，并做词形归一。"""
    tokens: list[str] = []
    for raw in _TOKEN_PATTERN.findall(text):
        normalized = normalize_keyword(raw)
        if not normalized or len(normalized) < 3:
            continue
        if normalized in STOPWORDS:
            continue
        # 去掉连写里遗留的空格片段，保留整体作为候选（如 self-supervised）
        tokens.append(normalized)
    return tokens


def candidate_phrases(tokens: list[str]) -> list[str]:
    """相邻词的二元短语候选，形如 object detection。"""
    phrases: list[str] = []
    for index in range(len(tokens) - 1):
        left, right = tokens[index], tokens[index + 1]
        if left == right:
            continue
        phrases.append(f"{left} {right}")
    return phrases


class KeywordExtractor:
    """稀疏 TF-IDF + TextRank 抽取器。

    用法：
        extractor = KeywordExtractor()
        extractor.fit(documents)          # 统计 df / idf；语料只有一篇也允许
        result = extractor.extract(title, abstract)
    """

    def __init__(self, *, ruleset_version: str = KEYWORD_RULESET_VERSION) -> None:
        self.ruleset_version = ruleset_version
        self.corpus_size = 0
        self.tier = select_tier(0)
        self.document_freq: Counter[str] = Counter()
        self.idf: dict[str, float] = {}
        self._fitted = False

    # ---------------------------------------------------------------- 拟合

    def fit(self, documents: list[str]) -> None:
        """统计文档频次并据此剪枝词表；同时按语料规模选定分档。

        语料为空时按「单篇」档处理（min_df=1、不启用短语），
        这样第一次保存论文时也能产出关键词。
        """
        self.corpus_size = len(documents)
        self.tier = select_tier(self.corpus_size)
        self.document_freq = Counter()

        for document in documents:
            tokens = tokenize(document)
            vocabulary = set(tokens)
            if self.tier.phrases_enabled:
                vocabulary.update(candidate_phrases(tokens))
            for term in vocabulary:
                self.document_freq[term] += 1

        self.idf = {}
        if self.corpus_size:
            total = self.corpus_size
            for term, freq in self.document_freq.items():
                if freq < self.tier.effective_min_df:
                    continue
                self.idf[term] = math.log((total + 1) / (freq + 1)) + 1
        self._fitted = True

    # ---------------------------------------------------------------- 抽取

    def extract(self, title: str, abstract: str | None = None) -> ExtractionResult:
        """抽取一篇文档的关键词。

        摘要缺失时只用标题，并在返回值里保持语料与参数信息，
        调用方（详情页）负责标注「关键词仅基于标题」。
        """
        if not self._fitted:
            self.fit([])

        text = title if not abstract else f"{title} {abstract}"
        tokens = tokenize(text)
        counts = Counter(tokens)

        phrase_counts: Counter[str] = Counter()
        if self.tier.phrases_enabled:
            for phrase in candidate_phrases(tokens):
                if self.document_freq.get(phrase, 0) >= self.tier.phrase_min_df:
                    phrase_counts[phrase] += 1

        # TF-IDF：idf 取自拟合语料；语料只有单篇时 idf 无区分度，退化为纯词频
        tfidf_scores: dict[str, float] = {}
        for term, count in {**counts, **phrase_counts}.items():
            if self.corpus_size >= 30:
                idf = self.idf.get(term)
                if idf is None:
                    continue
            else:
                idf = 1.0
            tfidf_scores[term] = (1 + math.log(count)) * idf

        textrank_scores = self._textrank([*tokens, *phrase_counts.keys()])

        top_tfidf = sorted(
            tfidf_scores.items(), key=lambda item: (-item[1], item[0])
        )[:TOP_TFIDF]
        top_textrank = sorted(
            textrank_scores.items(), key=lambda item: (-item[1], item[0])
        )[:TOP_TEXTRANK]

        merged: dict[str, ExtractedKeyword] = {}
        for name, score in top_tfidf:
            merged[name] = ExtractedKeyword(
                name=name,
                normalized=normalize_keyword(name),
                tfidf_score=round(score, 6),
            )
        for name, score in top_textrank:
            if name in merged:
                merged[name].textrank_score = round(score, 6)
                continue
            merged[name] = ExtractedKeyword(
                name=name,
                normalized=normalize_keyword(name),
                textrank_score=round(score, 6),
            )

        ordered = sorted(
            merged.values(),
            key=lambda item: (
                -((item.tfidf_score or 0) + (item.textrank_score or 0)),
                item.name,
            ),
        )[:MAX_PER_PAPER]
        for rank, keyword in enumerate(ordered):
            keyword.rank = rank

        return ExtractionResult(
            keywords=ordered,
            corpus_size=self.corpus_size,
            effective_min_df=self.tier.effective_min_df,
            phrases_enabled=self.tier.phrases_enabled,
            ruleset_version=self.ruleset_version,
        )

    def _textrank(self, tokens: list[str]) -> dict[str, float]:
        """在单篇文档的词共现图上迭代 PageRank，取分数较高的词。"""
        if not tokens:
            return {}
        graph: dict[str, dict[str, float]] = {}
        for index, token in enumerate(tokens):
            window = tokens[
                max(0, index - TEXTRANK_WINDOW) : index + TEXTRANK_WINDOW + 1
            ]
            for other in window:
                if other == token:
                    continue
                graph.setdefault(token, {})
                graph[token][other] = graph[token].get(other, 0.0) + 1.0
                graph.setdefault(other, {})

        nodes = list(graph)
        if not nodes:
            return {}
        scores = {node: 1.0 for node in nodes}
        for _ in range(TEXTRANK_ITERATIONS):
            updated: dict[str, float] = {}
            for node in nodes:
                incoming = 0.0
                for other in nodes:
                    neighbours = graph.get(other) or {}
                    weight = neighbours.get(node, 0.0)
                    if weight <= 0:
                        continue
                    total = sum(neighbours.values())
                    if total > 0:
                        incoming += scores[other] * weight / total
                updated[node] = (1 - TEXTRANK_DAMPING) + TEXTRANK_DAMPING * incoming
            scores = updated
        return scores

    # ---------------------------------------------------------------- 元信息

    def config_signature(self) -> str:
        """把影响结果的参数哈希成一个签名，便于识别「语料跨档」等配置变化。"""
        payload = "|".join(
            [
                self.ruleset_version,
                str(self.corpus_size),
                str(self.tier.effective_min_df),
                str(self.tier.phrase_min_df),
                str(self.tier.phrases_enabled),
                str(MAX_PER_PAPER),
                str(TOP_TFIDF),
                str(TOP_TEXTRANK),
                str(TEXTRANK_WINDOW),
            ]
        )
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def extract_single(title: str, abstract: str | None = None) -> ExtractionResult:
    """只有一篇文档时直接抽取（阶段 5 的单篇验收路径）。"""
    extractor = KeywordExtractor()
    extractor.fit([f"{title} {abstract}" if abstract else title])
    return extractor.extract(title, abstract)
