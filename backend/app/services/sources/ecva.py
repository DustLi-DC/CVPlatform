"""ECVA 解析（ECCV）。

实测结构（2026-09 核对）：
- 汇总页 `https://www.ecva.net/papers.php` 把所有年份放在同一页的折叠区里，
  按 `ECCV <年份> Papers` 分段；
- 条目形如
  `<dt class="ptitle"><br><a href=papers/eccv_2024/papers_ECCV/html/`
  `4_ECCV_2024_paper.php>标题</a></dt>`
  注意 **href 没有引号**，只用双引号正则匹配会漏掉全部条目；
- 详情页同样是 `<div id="papertitle">` 与 `<div id="abstract">`。

CVF 不收录 ECCV（实测 404），因此 ECCV 的数据只能来自本来源。
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass

from .cvf import PaperFields, _clean, _extract_div
from .http import fetch_text

SOURCE_NAME = "ecva"
BASE_URL = "https://www.ecva.net"

# 折叠区分段：ECCV 2024 Papers
_SECTION_PATTERN = re.compile(
    r"ECCV\s+(\d{4})\s+Papers(.*?)(?=ECCV\s+\d{4}\s+Papers|$)", re.S
)
# 条目：href 可能没有引号，因此分别匹配带引号与不带引号两种写法
_ENTRY_PATTERN = re.compile(
    r"<dt class=\"ptitle\">.*?<a href=[\"']?(papers/eccv_(\d{4})/papers_ECCV/html/"
    r"[^\"'>\s]+\.php)[\"']?>(.*?)</a>",
    re.S,
)


@dataclass(frozen=True)
class EcvaEntry:
    title: str
    paper_path: str
    year: int

    @property
    def landing_url(self) -> str:
        return f"{BASE_URL}/{self.paper_path}"


def parse_index(html: str, *, year: int | None = None) -> list[EcvaEntry]:
    """解析 ECVA 汇总页；给定 year 时只返回该年份的条目。

    先按年份分段，再在段内取条目，避免把其他年份算进来。
    """
    entries: list[EcvaEntry] = []
    sections = _SECTION_PATTERN.findall(html)
    if not sections:
        # 结构变化时退化为整页扫描，年份取自条目自身的路径
        sections = [("", html)]
    for section_year, body in sections:
        for path, path_year, raw_title in _ENTRY_PATTERN.findall(body):
            entry_year = int(path_year) if path_year else int(section_year or 0)
            if year is not None and entry_year != year:
                continue
            title = _clean(raw_title)
            if title:
                entries.append(EcvaEntry(title=title, paper_path=path, year=entry_year))
    return entries


def parse_paper(html: str, *, paper_path: str | None = None) -> PaperFields:
    """解析 ECVA 详情页；结构与 CVF 一致，复用同一套容器约定。"""
    authors_raw = _extract_div(html, "authors")
    authors = []
    if authors_raw:
        authors = [item.strip() for item in authors_raw.split(",") if item.strip()]

    pdf_match = None
    landing_url = f"{BASE_URL}/{paper_path}" if paper_path else None
    # 实测详情页里的链接形如 ../../../../papers/eccv_2024/papers_ECCV/papers/00529.pdf
    # 既不以 papers/ 开头也不带引号，因此匹配任意 .pdf 后再按详情页地址解析相对路径，
    # 否则 ECCV 的原文链接会全部取不到。
    for href in re.findall(r"href=[\"']?([^\"'>\s]+\.pdf)[\"']?", html):
        if "supp" in href.lower():
            continue  # 排除 supplementary 附件，只保留正文 PDF
        pdf_match = urllib.parse.urljoin(landing_url or BASE_URL, href)
        break

    return PaperFields(
        title=_extract_div(html, "papertitle"),
        authors=authors,
        abstract=_extract_div(html, "abstract"),
        pdf_url=pdf_match,
        landing_url=landing_url,
        source_id=paper_path,
    )


def fetch_index(
    year: int, *, timeout: float | None = None, retries: int | None = None
) -> list[EcvaEntry]:
    """抓取 ECVA 汇总页并取出指定年份的条目。"""
    html = fetch_text(
        f"{BASE_URL}/papers.php", source=SOURCE_NAME, timeout=timeout, retries=retries
    )
    return parse_index(html, year=year)


def fetch_paper(
    paper_path: str, *, timeout: float | None = None, retries: int | None = None
) -> PaperFields:
    html = fetch_text(
        f"{BASE_URL}/{paper_path}", source=SOURCE_NAME, timeout=timeout, retries=retries
    )
    return parse_paper(html, paper_path=paper_path)
