"""关键词规范化与关键词关联维护。

本模块只做**词形归一**（确定性、可逆语义），不做主题归并：
主题归并属于统计展示层，在阶段 6/7 由主题表承担，且不改写原始关键词。

阶段 5 的 TF-IDF + TextRank 抽取模块会复用本模块的 normalize_keyword 与
sync_paper_keywords，不重复实现。
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import UTC, datetime

from sqlmodel import Session, select

from ..config import KEYWORD_RULESET_VERSION
from ..models.entities import AppMeta, Keyword, Paper, PaperKeyword
from .maintenance import mark_analysis_changed

# 常见缩写与写法归一。只做确定性的等价替换，不做语义合并。
_CANONICAL_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\bthree[- ]dimensional\b", "3d"),
    (r"\bthree[- ]dimension\b", "3d"),
    (r"\b2[- ]dimensional\b", "2d"),
    (r"\btwo[- ]dimensional\b", "2d"),
    (r"\bmulti[- ]modal\b", "multimodal"),
    (r"\bself[- ]supervised\b", "self-supervised"),
    (r"\bstate of the art\b", "state-of-the-art"),
)

_NON_WORD = re.compile(r"[^\w\s\-+]", re.UNICODE)
_SPACES = re.compile(r"\s+")
# 以这些结尾的词不是复数；去掉尾部 s 会把词改坏（across→acros、analysis→analysi）。
# 不包含 -os：videos 要归到 video，而 -os 只保护 chaos 这类罕见词，
# 两相权衡下按「合并 video/videos」处理（实测 videos 影响 43 篇论文）。
_NOT_PLURAL = re.compile(r"(ss|us|is|as)$")
# 以 -(ss|x|z|ch|sh)es 结尾的名词复数应去掉整个 es：classes→class、boxes→box。
# 不包含 -ses：cases→case、uses→use 要去的是一个 s，按 es 去会得到 cas / us 这种错词。
_ES_PLURAL = re.compile(r"(sses|xes|zes|ches|shes)$")


def _singularize(token: str) -> str:
    """保守的单复数归一：只在有把握时去复数。

    宁可少归并，也不要把词改坏——归一形式是 keyword 表的唯一键，
    一旦把 across 变成 acros，详情页与图谱上显示的就是错词。
    """
    if len(token) < 4 or not token.endswith("s"):
        return token
    if _ES_PLURAL.search(token):
        return token[:-2]
    if _NOT_PLURAL.search(token):
        return token
    if token.endswith("ies"):
        return f"{token[:-3]}y"
    return token[:-1]


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def detect_language(name: str) -> str:
    """粗粒度语种判定：含中日韩统一表意文字即视为中文，其余按英文处理。"""
    for char in name:
        if "\u4e00" <= char <= "\u9fff":
            return "zh"
    return "en"


def normalize_keyword(name: str) -> str:
    """关键词归一化：NFKC → 小写 → 去首尾标点 → 折叠空白 → 单复数与常见缩写归一。

    这一级必须稳定可重复，因为它是 keyword 表的唯一键之一；
    同义/跨语言的合并交给主题归并层处理。
    """
    text = unicodedata.normalize("NFKC", name).strip().lower()
    for pattern, replacement in _CANONICAL_REPLACEMENTS:
        text = re.sub(pattern, replacement, text)
    text = text.replace("_", " ")
    text = _NON_WORD.sub(" ", text)
    # 逐词归一单复数，避免对整串做正则替换把 across 之类的词改坏
    text = " ".join(_singularize(token) for token in text.split())
    text = _SPACES.sub(" ", text).strip(" -")
    return text


def parse_keywords_json(raw: str | None) -> list[str]:
    """解析 keywords_source_json；内容非法时返回空列表而不是抛错。"""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def dump_keywords_json(keywords: list[str]) -> str | None:
    cleaned = [item.strip() for item in keywords if item.strip()]
    if not cleaned:
        return None
    return json.dumps(cleaned, ensure_ascii=False)


def upsert_keyword(
    session: Session,
    *,
    name: str,
    origin: str,
    ruleset_version: str = KEYWORD_RULESET_VERSION,
) -> Keyword | None:
    """按 (归一形式, 来源) 取回或创建关键词行；归一后为空则不创建。"""
    normalized = normalize_keyword(name)
    if not normalized:
        return None
    existing = session.exec(
        select(Keyword).where(
            Keyword.name_normalized == normalized,
            Keyword.origin == origin,
        )
    ).first()
    if existing is not None:
        return existing

    keyword = Keyword(
        name=name.strip(),
        name_normalized=normalized,
        language=detect_language(name),
        origin=origin,
        doc_freq=0,
        created_at=_now(),
    )
    session.add(keyword)
    session.flush()
    return keyword


def current_ruleset_version(session: Session) -> str:
    """读取 meta 中的当前关键词规则版本；缺失时回退到模块常量。"""
    row = session.get(AppMeta, "keyword_ruleset_version")
    if row is None or not row.value:
        return KEYWORD_RULESET_VERSION
    return row.value


def _replace_origin_keywords(
    session: Session,
    paper: Paper,
    *,
    origin: str,
    names: list[str],
    ruleset_version: str,
) -> None:
    """按“替换”语义同步某一来源的关键词关联。

    传入的列表就是该来源的**完整集合**：新增缺失的、更新顺序、**删除被移除的**。
    只增不删会让接口字段显示为空、而旧标签仍能在列表和检索里命中，两者长期不一致。
    这里只删关联，不删 keyword 行本身——同一关键词可能被其他论文引用，
    孤立关键词由显式维护任务按 doc_freq = 0 清理。
    """
    if paper.id is None:  # pragma: no cover - 调用方保证已 flush
        raise ValueError("paper 必须先持久化再关联关键词")

    desired: dict[int, int] = {}
    order: dict[int, int] = {}
    for rank, name in enumerate(names):
        keyword = upsert_keyword(
            session, name=name, origin=origin, ruleset_version=ruleset_version
        )
        if keyword is None or keyword.id is None:
            continue
        # 同一归一形式重复出现时保留首次出现的位次
        if keyword.id not in desired:
            desired[keyword.id] = rank
            order[keyword.id] = len(order)

    existing_rows = session.exec(
        select(PaperKeyword)
        .join(Keyword, Keyword.id == PaperKeyword.keyword_id)
        .where(
            PaperKeyword.paper_id == paper.id,
            Keyword.origin == origin,
            PaperKeyword.ruleset_version == ruleset_version,
        )
    ).all()

    existing_by_keyword = {row.keyword_id: row for row in existing_rows}
    for keyword_id, row in existing_by_keyword.items():
        if keyword_id not in desired:
            session.delete(row)
            continue
        if origin == "author" and row.rank != desired[keyword_id]:
            row.rank = desired[keyword_id]
            session.add(row)

    mark_analysis_changed(session)
    for keyword_id in desired:
        if keyword_id in existing_by_keyword:
            continue
        session.add(
            PaperKeyword(
                paper_id=paper.id,
                keyword_id=keyword_id,
                rank=desired[keyword_id],
                ruleset_version=ruleset_version,
                created_at=_now(),
            )
        )


def sync_paper_keywords(
    session: Session,
    paper: Paper,
    *,
    author_keywords: list[str],
    system_keywords: list[str] | None = None,
    ruleset_version: str | None = None,
) -> None:
    """写入/更新论文的关键词关联。

    - 作者关键词（origin=author）来自来源数据，只用于展示，不参与统计；
    - 系统关键词（origin=system）由阶段 5 的抽取模块传入，参与统计；
    - 传 None 表示“不改动该来源”，传列表表示“该来源的完整集合”，按替换语义同步；
    - 重复保存是幂等的：已存在的 (论文, 关键词, 版本) 不会重复写入；
    - 旧版本行不删除，按版本保留以便比对，读取与统计侧只认当前版本。
    """
    version = ruleset_version or current_ruleset_version(session)
    _replace_origin_keywords(
        session, paper, origin="author", names=author_keywords, ruleset_version=version
    )
    if system_keywords is not None:
        _replace_origin_keywords(
            session,
            paper,
            origin="system",
            names=system_keywords,
            ruleset_version=version,
        )


def clear_system_keywords(session: Session, paper_id: int) -> int:
    """清除某篇论文的系统关键词关联（作者关键词保留），返回删除条数。

    题目或摘要变化会使系统抽取结果失效时调用；作者关键词来自来源数据，不受影响。
    """
    rows = session.exec(
        select(PaperKeyword)
        .join(Keyword, Keyword.id == PaperKeyword.keyword_id)
        .where(PaperKeyword.paper_id == paper_id, Keyword.origin == "system")
    ).all()
    removed = 0
    for row in rows:
        session.delete(row)
        removed += 1
    if removed:
        mark_analysis_changed(session)
    return removed
