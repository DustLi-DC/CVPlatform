"""统计口径维护：分析集合版本号、数据修复与按需重算。

设计依据：开发设计与验收.md 第 4.4 节（缓存与失效）。

- 统计结果按「分析集合版本」缓存。任何会影响统计的写入（论文增删改、关键词写入、
  主题映射变化、数据修复）都必须调用 mark_analysis_changed，使缓存整体失效。
  这里用的是**显式自增计数**而不是时间过期：时间过期会给出「看起来新、实际过期」
  的结果，而漏记一次计数只会让缓存多留一轮，不会给出错误口径。
- 数据修复是显式动作（默认试运行），不隐式改写真实数据。
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from html import unescape

from sqlmodel import Session, select

from ..models.entities import AppMeta, Paper

logger = logging.getLogger("cvplatform.maintenance")

ANALYSIS_VERSION_KEY = "analysis_version"


def _now_key_value(session: Session, key: str, value: str) -> None:
    row = session.get(AppMeta, key)
    if row is None:
        session.add(AppMeta(key=key, value=value))
        return
    row.value = value
    session.add(row)


def mark_analysis_changed(session: Session) -> int:
    """把分析集合版本自增，返回新版本号。

    由所有影响统计的写入路径调用；统计接口据此判断缓存是否仍然有效。
    """
    row = session.get(AppMeta, ANALYSIS_VERSION_KEY)
    current = int(row.value) if row is not None and row.value.isdigit() else 0
    next_version = current + 1
    _now_key_value(session, ANALYSIS_VERSION_KEY, str(next_version))
    return next_version


def read_analysis_version(session: Session) -> int:
    """读取当前分析集合版本；从未写入过时返回 0（此时统计缓存必然是空的）。"""
    row = session.get(AppMeta, ANALYSIS_VERSION_KEY)
    if row is None or not row.value.isdigit():
        return 0
    return int(row.value)


_ENTITY_PATTERN = re.compile(r"&(?:#x?[0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]{1,10});")


def _entity_context(text: str) -> str:
    """截取第一个实体附近的片段，便于人工核对到底改了什么。"""
    match = _ENTITY_PATTERN.search(text)
    if match is None:  # pragma: no cover - 调用方只在含实体时使用
        return text[:80]
    start = max(0, match.start() - 40)
    return text[start : match.end() + 40]


def repair_html_entities(session: Session, *, apply: bool = False) -> dict[str, object]:
    """修复摘要里残留的 HTML 实体（如 &#x27; 与 &quot;）。

    来源页面返回的是 HTML，解析时若不做实体还原，存下来的摘要会带 &#x27;，
    详情页显示成「iteration&#x27;s」，关键词抽取也会产出 x27、quot 这类词条
    （实测 182 篇 CVF 论文受影响）。这里按实体还原做定点修复，
    不重写正文、不补齐缺失字段；默认只统计不写入。
    """
    papers = list(session.exec(select(Paper).where(Paper.abstract.is_not(None))).all())
    scanned = 0
    changed = 0
    kinds: Counter[str] = Counter()
    samples: list[dict[str, str]] = []
    for paper in papers:
        scanned += 1
        original = paper.abstract or ""
        if "&" not in original:
            continue
        repaired = unescape(original)
        if repaired == original:
            continue
        changed += 1
        for entity in _ENTITY_PATTERN.findall(original):
            kinds[f"{entity} → {unescape(entity)}"] += 1
        if len(samples) < 3:
            samples.append(
                {
                    "code": paper.code,
                    "before": _entity_context(original),
                    "after": _entity_context(repaired),
                }
            )
        if apply:
            paper.abstract = repaired
            session.add(paper)
    if apply and changed:
        mark_analysis_changed(session)
        session.flush()
    return {
        "scanned": scanned,
        "changed": changed,
        "applied": apply,
        "entity_kinds": dict(kinds.most_common(10)),
        "samples": samples,
    }
