"""主题归并层：把版本化主题表载入数据库，并把关键词映射到主题。

设计依据：开发设计与验收.md 第 6 章（已确认采用方案 A）。

- 主题表是**可提交的版本化数据文件** `backend/app/data/topics_v1.json`，
  含版本、样本依据与主题清单（slug / name / group_name / aliases）。
- 归并**不改写原始关键词**：keyword 行保留系统抽到的原词，
  只把 topic_id 指向主题；统计按主题聚合，详情页仍展示原始关键词。
- 映射不到主题的关键词如实保留为「未归类」，不强行塞进某个主题、也不丢弃。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session, select

from ..models.entities import Topic, TopicAlias
from .keywords import normalize_keyword
from .maintenance import mark_analysis_changed

TOPICS_FILE = Path(__file__).resolve().parents[1] / "data" / "topics_v1.json"


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class TopicEntry:
    """主题表中的一个主题。别名一律保存归一形式，便于与 keyword 直接比对。"""

    slug: str
    name: str
    group_name: str | None
    aliases: tuple[str, ...]


def load_topic_file(path: Path | None = None) -> tuple[str, list[TopicEntry]]:
    """读取主题表文件，返回 (版本, 主题列表)。

    文件缺失或格式非法时抛出 ValueError，由调用方决定提示方式——
    统计不能在「主题表读不出来」的情况下静默按关键词聚合，那会让口径悄悄变化。
    """
    target = path or TOPICS_FILE
    if not target.exists():
        raise ValueError(f"主题表文件不存在：{target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"主题表不是合法 JSON：{target}") from error

    version = str(payload.get("版本") or "").strip()
    raw_topics = payload.get("主题")
    if not version or not isinstance(raw_topics, list) or not raw_topics:
        raise ValueError(f"主题表缺少「版本」或「主题」字段：{target}")

    entries: list[TopicEntry] = []
    for item in raw_topics:
        slug = str(item.get("slug") or "").strip()
        name = str(item.get("name") or "").strip()
        if not slug or not name:
            raise ValueError(f"主题缺少 slug 或 name：{item!r}")
        aliases: list[str] = []
        for alias in item.get("aliases") or []:
            normalized = normalize_keyword(str(alias))
            if normalized and normalized not in aliases:
                aliases.append(normalized)
        # 主题名本身也作为别名，使「主题名直接作为关键词」的写法也能映射
        normalized_name = normalize_keyword(name)
        if normalized_name and normalized_name not in aliases:
            aliases.append(normalized_name)
        entries.append(
            TopicEntry(
                slug=slug,
                name=name,
                group_name=(item.get("group_name") or None),
                aliases=tuple(aliases),
            )
        )
    return version, entries


def sync_topics(session: Session, *, path: Path | None = None) -> dict[str, object]:
    """把主题表写入 topic / topic_alias，并重算关键词的主题映射。

    幂等：重复执行按 slug 更新名称与分组、按别名更新归属，
    文件里已删除的主题置为 is_active = 0（不物理删除，历史统计口径可回溯）。
    """
    version, entries = load_topic_file(path)
    created = 0
    updated = 0
    alias_count = 0

    existing_topics = {topic.slug: topic for topic in session.exec(select(Topic)).all()}
    kept_slugs: set[str] = set()

    for entry in entries:
        kept_slugs.add(entry.slug)
        topic = existing_topics.get(entry.slug)
        if topic is None:
            topic = Topic(
                slug=entry.slug,
                name=entry.name,
                group_name=entry.group_name,
                is_active=True,
                sort_order=len(kept_slugs),
                created_at=_now(),
            )
            session.add(topic)
            session.flush()
            created += 1
        else:
            topic.name = entry.name
            topic.group_name = entry.group_name
            topic.is_active = True
            topic.sort_order = len(kept_slugs)
            session.add(topic)
            updated += 1
        if topic.id is None:  # pragma: no cover - flush 后必有 id
            raise ValueError("主题未持久化")

        # 别名唯一：同一别名只能属于一个主题，跨主题冲突时以文件顺序为准
        for alias in entry.aliases:
            row = session.exec(
                select(TopicAlias).where(TopicAlias.alias_normalized == alias)
            ).first()
            if row is None:
                session.add(TopicAlias(topic_id=topic.id, alias_normalized=alias))
                alias_count += 1
            elif row.topic_id != topic.id:
                row.topic_id = topic.id
                session.add(row)
                alias_count += 1

    deactivated = 0
    for slug, topic in existing_topics.items():
        if slug in kept_slugs or not topic.is_active:
            continue
        topic.is_active = False
        session.add(topic)
        deactivated += 1

    session.flush()
    mapped = map_keywords_to_topics(session)
    # 主题归属变化会改变统计分组，必须让分析集合版本自增以失效缓存
    mark_analysis_changed(session)
    return {
        "topic_version": version,
        "topics": len(entries),
        "created": created,
        "updated": updated,
        "aliases": alias_count,
        "deactivated": deactivated,
        "mapped_keywords": mapped,
    }


def map_keywords_to_topics(session: Session) -> int:
    """按别名把系统关键词映射到主题，返回被映射的关键词行数。

    只处理 origin = 'system' 的关键词：作者关键词不参与统计，也不需要主题归属。
    找不到别名的关键词 topic_id 置空——统计侧把它归入「未归类」，如实展示。
    """
    session.execute(
        text(
            """
            UPDATE keyword
               SET topic_id = (
                   SELECT ta.topic_id
                     FROM topic_alias ta
                     JOIN topic t ON t.id = ta.topic_id
                    WHERE ta.alias_normalized = keyword.name_normalized
                      AND t.is_active = 1
               )
             WHERE origin = 'system'
            """
        )
    )
    session.flush()
    row = session.execute(
        text("SELECT COUNT(*) FROM keyword WHERE origin = 'system' AND topic_id IS NOT NULL")
    ).first()
    return int(row[0]) if row else 0
