"""CVF Open Access 解析（CVPR / ICCV）。

实测结构（2026-09 核对，见 开发设计与验收.md 第 2.4 节）：
- 索引页 `https://openaccess.thecvf.com/<CONF><YEAR>?day=all`
  每条为 `<dt class="ptitle">…<a href="/content/<CY>/html/<slug>_paper.html">标题</a></dt>`；
- 详情页 `<div id="papertitle">` 与 `<div id="abstract">` 两个固定容器，
  作者在 `<div id="authors">`，PDF 链接形如 `/content/<CY>/papers/<slug>_paper.pdf`。

CVF 不含 ECCV，ECCV 见 sources/ecva.py。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import unescape

from .http import fetch_text

SOURCE_NAME = "cvf"
BASE_URL = "https://openaccess.thecvf.com"

# 索引页里的论文条目：标题与其详情页路径
_ENTRY_PATTERN = re.compile(
    r'<dt class="ptitle">.*?<a href="(/content/[^"]+?/html/[^"]+?paper\.html)">'
    r"(.*?)</a>",
    re.S,
)
_TAG_PATTERN = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class IndexEntry:
    """索引页里的一条论文条目：标题与详情页地址。"""

    title: str
    paper_path: str

    @property
    def landing_url(self) -> str:
        return f"{BASE_URL}{self.paper_path}"


@dataclass
class PaperFields:
    """从详情页解析出的字段；缺失字段保持 None，不用占位文本填充。"""

    title: str | None = None
    authors: list[str] = field(default_factory=list)
    abstract: str | None = None
    pdf_url: str | None = None
    landing_url: str | None = None
    source_id: str | None = None


def _clean(fragment: str) -> str:
    """去标签、解析 HTML 实体并折叠空白。

    必须先解析实体再折叠空白：CVF 摘要里的撇号写作 &#x27;、引号写作 &quot;，
    不解析会同时污染详情页显示与关键词抽取——实测 182 篇 CVF 论文的摘要
    带有实体，抽取结果里出现过 x27 与 quot 这类无意义词条。
    顺序为「先去标签再解析实体」，这样 &lt;div&gt; 会如实还原成文本而不是被当标签删掉。
    """
    text = _WHITESPACE.sub(" ", _TAG_PATTERN.sub(" ", fragment))
    return unescape(text).strip()


def _extract_div(html: str, element_id: str) -> str | None:
    match = re.search(rf'<div id="{element_id}"[^>]*>(.*?)</div>', html, re.S)
    if match is None:
        return None
    value = _clean(match.group(1))
    return value or None


def parse_index(html: str) -> list[IndexEntry]:
    """解析 CVF 会议年份索引页，返回条目列表（顺序即来源页面顺序）。"""
    entries: list[IndexEntry] = []
    for path, raw_title in _ENTRY_PATTERN.findall(html):
        title = _clean(raw_title)
        if title:
            entries.append(IndexEntry(title=title, paper_path=path))
    return entries


def parse_paper(html: str, *, paper_path: str | None = None) -> PaperFields:
    """解析 CVF 详情页，取出标题、作者、摘要与 PDF 链接。"""
    authors_raw = _extract_div(html, "authors")
    authors = []
    if authors_raw:
        authors = [item.strip() for item in authors_raw.split(",") if item.strip()]

    pdf_match = re.search(r'href="(/content/[^"]+?/papers/[^"]+?\.pdf)"', html)

    return PaperFields(
        title=_extract_div(html, "papertitle"),
        authors=authors,
        abstract=_extract_div(html, "abstract"),
        pdf_url=f"{BASE_URL}{pdf_match.group(1)}" if pdf_match else None,
        landing_url=f"{BASE_URL}{paper_path}" if paper_path else None,
        source_id=paper_path,
    )


def fetch_index(
    conference: str,
    year: int,
    *,
    timeout: float | None = None,
    retries: int | None = None,
) -> list[IndexEntry]:
    """抓取并解析某会议年份的索引页（一次请求拿到全部条目）。"""
    url = f"{BASE_URL}/{conference}{year}?day=all"
    html = fetch_text(url, source=SOURCE_NAME, timeout=timeout, retries=retries)
    return parse_index(html)


def fetch_paper(
    paper_path: str,
    *,
    timeout: float | None = None,
    retries: int | None = None,
) -> PaperFields:
    """抓取并解析单篇详情页。"""
    html = fetch_text(
        f"{BASE_URL}{paper_path}", source=SOURCE_NAME, timeout=timeout, retries=retries
    )
    return parse_paper(html, paper_path=paper_path)
