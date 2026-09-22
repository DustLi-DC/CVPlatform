"""OpenAlex 在线检索（本地未命中时的兜底来源）。

实测要点（见 开发设计与验收.md 第 2.1、2.4 节）：
- 按题目检索返回的候选**有明显噪声**，必须做相似度排序并由使用者确认，不能取第一条；
- 会议归属经常缺失：`primary_location.source` 常为 null，CVPR/ICCV 可从 DOI 串识别，
  但 ECCV 的 DOI 指向 Springer，**无法据此推断**，因此会议可能为 None；
- 同一篇论文可能同时以会议版与 arXiv 预印本出现，会议版往往没有摘要，
  预印本有摘要但没有会议归属——两者都需要如实呈现给使用者判断；
- 摘要是 `{词: [位置]}` 形式的倒排索引，需要按位置还原成文本。
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field

from .http import fetch_json

SOURCE_NAME = "openalex"
ENDPOINT = "https://api.openalex.org/works"
MAILTO = "course@example.com"

# DOI 前缀里能识别出的会议（ECCV 走 Springer，识别不出）
_DOI_CONFERENCE = (
    ("cvpr", "CVPR"),
    ("iccv", "ICCV"),
)


@dataclass
class RemoteCandidate:
    """在线检索到的一条候选论文。"""

    source: str
    source_id: str
    title: str
    year: int | None = None
    conference: str | None = None
    venue: str | None = None
    doi: str | None = None
    landing_url: str | None = None
    pdf_url: str | None = None
    abstract: str | None = None
    authors: list[str] = field(default_factory=list)
    work_type: str | None = None
    match_score: float = 0.0
    already_exists: bool = False
    existing_code: str | None = None
    notes: list[str] = field(default_factory=list)


def restore_abstract(inverted_index: object) -> str | None:
    """把 `{词: [位置]}` 的倒排索引还原成摘要文本；缺字段时返回 None。"""
    if not isinstance(inverted_index, dict):
        return None
    positions: dict[int, str] = {}
    for word, offsets in inverted_index.items():
        if not isinstance(offsets, list):
            continue
        for offset in offsets:
            if isinstance(offset, int):
                positions[offset] = str(word)
    if not positions:
        return None
    return " ".join(positions[index] for index in sorted(positions)) or None


def infer_conference(doi: str | None, venue: str | None) -> str | None:
    """从 DOI 或会议名推断三大会议；推不出来返回 None（不猜）。"""
    haystack = " ".join(filter(None, [doi or "", venue or ""])).lower()
    for marker, conference in _DOI_CONFERENCE:
        if marker in haystack:
            return conference
    if "european conference on computer vision" in haystack:
        return "ECCV"
    return None


def parse_work(work: dict) -> RemoteCandidate:
    """把 OpenAlex 的一条结果转换为候选对象。"""
    primary = work.get("primary_location") or {}
    best_oa = work.get("best_oa_location") or {}
    source_info = primary.get("source") or {}
    venue = source_info.get("display_name")
    doi = work.get("doi")

    authors: list[str] = []
    for authorship in work.get("authorships") or []:
        author = (authorship or {}).get("author") or {}
        name = author.get("display_name")
        if name:
            authors.append(str(name))

    notes: list[str] = []
    if work.get("type") == "preprint":
        notes.append("该候选为预印本，不是会议正式版本")
    if not work.get("abstract_inverted_index"):
        notes.append("该来源没有提供摘要")

    return RemoteCandidate(
        source=SOURCE_NAME,
        source_id=str(work.get("id") or ""),
        title=str(work.get("title") or "").strip(),
        year=work.get("publication_year"),
        conference=infer_conference(doi, venue),
        venue=venue,
        doi=doi,
        landing_url=primary.get("landing_page_url") or doi,
        pdf_url=best_oa.get("pdf_url"),
        abstract=restore_abstract(work.get("abstract_inverted_index")),
        authors=authors,
        work_type=work.get("type"),
        notes=notes,
    )


def parse_search(payload: object) -> list[RemoteCandidate]:
    """解析检索响应；结构不符时返回空列表而不是抛错。"""
    if not isinstance(payload, dict):
        return []
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    return [parse_work(item) for item in results if isinstance(item, dict)]


def search_by_title(
    title: str,
    *,
    per_page: int = 8,
    timeout: float | None = None,
    retries: int | None = None,
) -> list[RemoteCandidate]:
    """按题目检索候选论文。"""
    query = urllib.parse.quote(title.strip())
    url = f"{ENDPOINT}?search={query}&per-page={per_page}&mailto={MAILTO}"
    payload = fetch_json(
        url,
        source=SOURCE_NAME,
        timeout=timeout,
        retries=retries,  # type: ignore[call-arg]
    )
    return parse_search(payload)


def normalize_title_for_match(title: str) -> str:
    """用于相似度比较的标题归一化：只保留字母数字与空格。"""
    lowered = title.lower().replace("-", " ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", lowered)).strip()


def token_set_similarity(left: str, right: str) -> float:
    """标题相似度：词集合的 Jaccard 系数（0–1）。

    用词集合而不是字符序列，能容忍副标题、标点与语序差异；
    这里是给使用者排序用的参考值，不用于自动选定候选。
    """
    left_tokens = set(normalize_title_for_match(left).split())
    right_tokens = set(normalize_title_for_match(right).split())
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = left_tokens & right_tokens
    union = left_tokens | right_tokens
    return round(len(intersection) / len(union), 4)
