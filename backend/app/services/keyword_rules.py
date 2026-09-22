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

# 候选词：以字母或数字开头、含「词-词」连写的词条（如 self-supervised、3dgs），长度下限 3。
# 数字开头的补充分支覆盖 3d / 2d / 4d 这类只有两个字符的真实写法——
# 它们此前被整体丢弃，导致「3d gaussian splatting」只能退化成「gaussian splatting」。
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-]{2,}|[0-9][A-Za-z]{1,2}")
# 纯数字（年份、编号）不是关键词，需至少含一个字母
_HAS_LETTER = re.compile(r"[A-Za-z]")
# 数字开头的短形式（3d / 2d）在归一后只有两个字符，是有效的领域写法，需放行长度的下限
_SHORT_NUMERIC_FORM = re.compile(r"^[0-9][a-z]{1,2}$")

# 链接与联系方式：改写自 1200 篇真实摘要的实测噪声源。
# arXiv 摘要普遍带「code is available at https://github.com/...」这类样板句，
# 直接分词会产出 http / github / com 等词条（实测 df 分别为 434 / 431 / 323，
# 位列全语料前 20），并让「http github」成为最高频短语（df 314，占 26.2%）。
_URL_PATTERN = re.compile(r"https?://\S+|www\.\S+|\b[\w.+-]+@[\w-]+\.[\w.]+\b")

# 英语功能词与学术套话：这些词在摘要里高频出现但不指示研究方向。
# 三段文本在编译期拼接后统一切分：
#   1) 英语功能词与通用动词（阶段 5 初版）
#   2) 代码/链接/出版样板词（阶段 7 依据 1200 篇真实样本补入，kw-v3）
#   3) 学术行文与评价套话（同上；实测 demonstrate 43.8%、existing 41.2%）
_STOPWORD_TEXT = (
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
    """
    """
    http https www github gitlab com org net io arxiv doi email
    code codes available publicly release released project page pages url link
    supplementary appendix supplemental bibtex copyright license licence
    reserved rights ieee springer proceedings
    """
    """
    demonstrate demonstrates demonstrated existing extensive outperform outperforms
    address addresses challenge challenges challenging significant effective
    effectively effectiveness accuracy accurate benchmark benchmarks framework
    frameworks module modules application applications process processes
    strategy strategies scenario scenarios setting settings insight insights
    finding findings previous previously recent recently multiple diverse
    often due via while across between through during prior issue issues
    enhance enhances leverage leverages design designs enable enables trained
    training train validation ablation ablations baseline baselines sota
    set sets space spaces quality human knowledge map maps information
    generally overall achieve validate evaluated further specifically
    """
)

STOPWORDS: frozenset[str] = frozenset(_STOPWORD_TEXT.split())

# 只作短语成分的通用词：保留在分词结果里（否则短语无法形成），
# 但**永不单独作为关键词出现**。实测这些裸词在 kw-v2 里占据了榜单首位
# （image 出现于 623/1200 篇、data 374 篇、feature 399 篇），却说明不了任何方向。
# 例：image 不单独成词，但 image generation / image editing / image retrieval 照常成词。
BARE_GENERIC: frozenset[str] = frozenset(
    """
    image images data network networks feature features object objects visual
    scene scenes point points field fields view views class classes category
    categories token tokens memory text prompt prompts embedding embeddings
    estimation representation representations learning generation motion
    prediction predictions pixel pixels sample samples sample-level input
    output information knowledge prior performance result module map maps
    size level quality space process strategy task vision computer method
    """
    # 阶段 7 复核 kw-v3 榜单时补入：这些词在真实榜单里排在前面但单独看不出方向，
    # 它们的方向含义由短语（如 point cloud、domain adaptation、noisy label）承载。
    """
    semantic cloud temporal frame frames local global region regions
    content structure structures source target domain stage stages detail
    details function functions layer layers body user metric parameter
    modeling understanding distribution query queries dynamic latent noise
    label labels annotation annotations real-world synthetic sparse dense
    implicit geometric hierarchical sampling optimization control background
    interaction spatial aspect factor ability automatic standard specific
    encoder decoder module mask shift patch token-level
    """
    # 第二轮复核未归类榜单后补入：这些词单独出现时同样说明不了方向
    """
    instance instances deep real environment environments example examples
    single attribute attributes constraint constraints generate generated
    loss losses time vector vectors weight weights computational part parts
    2d adaptive dataset-level
    """.split()
)

# 本身有方向含义、但在同一篇里已被更具体的短语覆盖时不再单列的裸词。
# 例：选中了 object detection 就不必再列 detection；
# 选中了 pose estimation 就不必再列 pose 与 estimation。
SUPPRESS_WHEN_IN_PHRASE: frozenset[str] = frozenset(
    """
    detection segmentation diffusion attention transformer depth pose flow
    tracking recognition classification reconstruction synthesis rendering
    editing retrieval captioning translation distillation pruning quantization
    localization matching alignment registration completion super-resolution
    inpainting restoration compression caption summarization reasoning
    """.split()
)

# 分档参数：语料规模 → (最小文档频次, 短语最小文档频次, 是否启用短语)
TIERS: tuple[tuple[int, int, int, bool], ...] = (
    # (语料上限, effective_min_df, phrase_min_df, phrases_enabled)
    (30, 1, 0, False),
    (200, 2, 3, True),
    # kw-v3：短语阈值由 20 降到 5。实测 1200 篇语料在 df ≥ 20 时只剩 102 个短语，
    # 而 df ≥ 5 有 1257 个（df ≥ 3 有 3665 个，噪声偏多），
    # 原阈值使 top 关键词几乎全是单词，方向词（object detection 等）反而进不了榜。
    (5000, 5, 5, True),
    # kw-v4：语料扩到约 2.9 万篇（2020—2026 六个年份的完整论文集）后，固定阈值已经没有意义：
    # 实测 df ≥ 5 相当于「出现在 0.017% 的论文里」，单词候选 13719 个、短语候选 65517 个，
    # 绝大多数是长尾噪声。按语料规模抬到 min_df=20（0.069%，6292 个词）、
    # phrase_min_df=50（0.17%，2065 个短语），真实术语仍有很高频次
    # （object detection 1803、point cloud 1649、semantic segmentation 1325、pose estimation 929）。
    (10**9, 20, 50, True),
)

# 短语识别只用文档频次，**没有**采用设计文档 5.1 提到的互信息（PMI）阈值。
# 这是本轮在 1200 篇真实样本上测算后的结论（见 数据覆盖与来源.md 的复现命令）：
# PMI 偏向「两个罕见词偶遇」，会同时压掉噪声与真正的方向词，两者在数值上交错，
# 找不到可用的分界点——
#   优质术语：object detection 0.66、semantic segmentation 0.86、vision transformer 0.51、
#             deep learning -0.08、image generation -1.37、representation learning -1.43
#   噪声短语：current frame -0.74、image pixel -1.80、detection semantic -2.11
# 取 PMI ≥ 0 会删掉 422/822 个短语（含上面一半的优质术语），
# 取更高阈值更会把方向词清空。因此保留 df 阈值，并把短语噪声交给
# 主题别名表与统计口径消化；若将来引入词性/依存分析再重新评估。

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
    """分词：先剔除链接，再保留长度 ≥ 3 且含字母的英文词与连写词，并做词形归一。"""
    tokens: list[str] = []
    for raw in _TOKEN_PATTERN.findall(_URL_PATTERN.sub(" ", text)):
        if not _HAS_LETTER.search(raw):
            continue
        normalized = normalize_keyword(raw)
        if not normalized:
            continue
        if len(normalized) < 3 and not _SHORT_NUMERIC_FORM.match(normalized):
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

        # 通用词抑制：同一篇里已被短语覆盖的裸词不再单列（见 SUPPRESS_WHEN_IN_PHRASE）
        merged = self._suppress_generic_heads(merged)

        # 回填：抑制可能让结果不足 MAX_PER_PAPER，用剩余候选中分数最高的补齐，
        # 否则一篇论文会因为「image / data / learning 这些词被短语覆盖」而只剩三五个词。
        self._backfill(merged, tfidf_scores, textrank_scores)

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

    def _suppress_generic_heads(
        self, merged: dict[str, ExtractedKeyword]
    ) -> dict[str, ExtractedKeyword]:
        """去掉两类不具方向性的裸词，短语一律保留。

        1. BARE_GENERIC：本身太泛，永不单独作关键词（image / data / feature 等）；
        2. SUPPRESS_WHEN_IN_PHRASE：本身有含义，但同篇已被更具体的短语覆盖
           （选了 object detection 就不再列 detection）。
        """
        covered: set[str] = set()
        for name in merged:
            if " " in name:
                covered.update(name.split())
        kept: dict[str, ExtractedKeyword] = {}
        for name, keyword in merged.items():
            if " " in name:
                kept[name] = keyword
                continue
            if name in BARE_GENERIC:
                continue
            if name in SUPPRESS_WHEN_IN_PHRASE and name in covered:
                continue
            kept[name] = keyword
        return kept

    def _backfill(
        self,
        merged: dict[str, ExtractedKeyword],
        tfidf_scores: dict[str, float],
        textrank_scores: dict[str, float],
    ) -> None:
        """用剩余候选按分数补齐到 MAX_PER_PAPER，避免抑制后关键词过少。

        候选取两条打分路径的并集，排除停用词以外的通用裸词在被短语覆盖时的重复项，
        仍然按「两条路径分数之和」排序，与最终排序口径一致。
        """
        if len(merged) >= MAX_PER_PAPER:
            return
        covered: set[str] = set()
        for name in merged:
            if " " in name:
                covered.update(name.split())
        candidates = {
            name: (tfidf_scores.get(name, 0.0) + textrank_scores.get(name, 0.0))
            for name in {**tfidf_scores, **textrank_scores}
            if name not in merged
            and name not in BARE_GENERIC
            and not (name in covered and name in SUPPRESS_WHEN_IN_PHRASE)
        }
        for name, _ in sorted(candidates.items(), key=lambda item: (-item[1], item[0])):
            if len(merged) >= MAX_PER_PAPER:
                break
            merged[name] = ExtractedKeyword(
                name=name,
                normalized=normalize_keyword(name),
                tfidf_score=round(tfidf_scores[name], 6)
                if name in tfidf_scores
                else None,
                textrank_score=round(textrank_scores[name], 6)
                if name in textrank_scores
                else None,
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
        """把影响结果的参数哈希成一个签名，便于识别「语料跨档」等配置变化。

        除分档参数外，还包含词表指纹（停用词 / 只作短语成分的通用词 / 短语覆盖抑制），
        否则改了词表而忘记提升版本号时，签名不变、无从发现口径已经变了。
        """
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
                self._vocabulary_fingerprint(),
            ]
        )
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _vocabulary_fingerprint() -> str:
        """词表指纹：三份词表按字典序拼接后哈希，词表的任何增删都会改变它。"""
        parts = [
            "\n".join(sorted(STOPWORDS)),
            "\n".join(sorted(BARE_GENERIC)),
            "\n".join(sorted(SUPPRESS_WHEN_IN_PHRASE)),
        ]
        return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]


def extract_single(title: str, abstract: str | None = None) -> ExtractionResult:
    """只有一篇文档时直接抽取（阶段 5 的单篇验收路径）。"""
    extractor = KeywordExtractor()
    extractor.fit([f"{title} {abstract}" if abstract else title])
    return extractor.extract(title, abstract)
