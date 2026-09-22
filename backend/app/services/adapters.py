"""完整字段数据集的导入适配器（阶段 6 任务第 8 条）。

课程可能提供字段已经齐全的数据集（题目、会议、年份、摘要、关键词、链接），
这类数据不需要联网检索，但**必须复用同一套清洗、去重与关键词逻辑**，
否则同一篇论文从两条路径进来会产生两种结果。

支持两种输入：
- JSON：数组，或 `{"papers": [...]}`；
- CSV：列名沿用数据契约（title 必填，其余选填）。

字段映射尽量宽松：`keywords` 接受数组或逗号分隔字符串，
`authors` 同理。缺失字段保持为空，不用占位文本填充。
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from pathlib import Path

from ..config import CONFERENCES, KEYWORD_RULESET_VERSION
from .keyword_job import process_pending
from .keywords import sync_paper_keywords
from .keyword_job import _now
from .papers import ApiError, save_paper

# 可识别的字段别名，便于兼容不同数据集的小差异
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "title": ("title", "题目", "name"),
    "conference": ("conference", "venue", "会议"),
    "year": ("year", "年份"),
    "abstract": ("abstract", "summary", "摘要"),
    "authors": ("authors", "作者"),
    "keywords": ("keywords", "author_keywords", "关键词"),
    "system_keywords": ("system_keywords", "extracted_keywords", "系统关键词"),
    "landing_url": ("landing_url", "url", "link", "原文链接"),
    "pdf_url": ("pdf_url", "pdf", "pdf链接"),
    "source": ("source", "来源"),
    "source_id": ("source_id", "id", "编号"),
    "retrieved_at": ("retrieved_at", "fetched_at", "采集时间", "获取时间"),
}


@dataclass
class DatasetRecord:
    """适配后的一条记录；无法识别的字段一律为 None。"""

    title: str
    conference: str | None = None
    year: int | None = None
    abstract: str | None = None
    authors: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    system_keywords: list[str] = field(default_factory=list)
    retrieved_at: str | None = None
    landing_url: str | None = None
    pdf_url: str | None = None
    source: str = "dataset"
    source_id: str | None = None
    problems: list[str] = field(default_factory=list)


@dataclass
class AdapterResult:
    """导入结果：逐条统计，失败原因保留下来。"""

    total: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)

    @property
    def imported(self) -> int:
        return self.created + self.updated


def _pick(row: dict, field_name: str) -> object | None:
    """按别名取原始值；**不做字符串化**，否则 JSON 里的数组会变成 Python repr。"""
    for alias in FIELD_ALIASES.get(field_name, (field_name,)):
        for key, value in row.items():
            if str(key).strip().lower() == alias.lower() and value not in (None, ""):
                return value
    return None


def _as_text(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple, dict)):
        return None
    text = str(value).strip()
    return text or None


def _split_list(value: object | None) -> list[str]:
    """接受数组、JSON 数组字符串或逗号分隔字符串。"""
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    return [
        item.strip()
        for item in text.replace("，", ",").replace("；", ",").split(",")
        if item.strip()
    ]


def to_record(row: dict) -> DatasetRecord:
    """把原始行转换成适配后的记录，并记录字段问题。"""
    title = _as_text(_pick(row, "title")) or ""
    record = DatasetRecord(
        title=title,
        authors=_split_list(_pick(row, "authors")),
        keywords=_split_list(_pick(row, "keywords")),
        system_keywords=_split_list(_pick(row, "system_keywords")),
        retrieved_at=_as_text(_pick(row, "retrieved_at")),
        abstract=_as_text(_pick(row, "abstract")),
        landing_url=_as_text(_pick(row, "landing_url")),
        pdf_url=_as_text(_pick(row, "pdf_url")),
        source=_as_text(_pick(row, "source")) or "dataset",
        source_id=_as_text(_pick(row, "source_id")),
    )

    conference = _as_text(_pick(row, "conference"))
    if conference:
        upper = conference.upper()
        if upper in CONFERENCES:
            record.conference = upper
        else:
            record.problems.append(f"会议取值无法识别：{conference}")

    year = _as_text(_pick(row, "year"))
    if year:
        try:
            parsed_year = int(float(year))
        except ValueError:
            record.problems.append(f"年份无法识别：{year}")
        else:
            if 1900 < parsed_year < 2100:
                record.year = parsed_year
            else:
                record.problems.append(f"年份超出合理范围：{year}")

    if not title:
        record.problems.append("缺少题目")
    elif len(title) < 8:
        record.problems.append("题目过短")
    return record


def load_records(path: Path) -> list[DatasetRecord]:
    """读取数据集文件（JSON 或 CSV）并转换成记录列表。"""
    if not path.exists():
        raise ApiError(404, "dataset_not_found", f"数据集文件不存在：{path}")
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig", errors="replace")

    rows: list[dict]
    if path.suffix.lower() == ".json":
        payload = json.loads(text)
        if isinstance(payload, dict):
            payload = payload.get("papers") or payload.get("items") or []
        if not isinstance(payload, list):
            raise ApiError(400, "invalid_dataset", "JSON 结构无法识别：需要数组或 {papers: [...]}。")
        rows = [item for item in payload if isinstance(item, dict)]
    elif path.suffix.lower() == ".csv":
        rows = list(csv.DictReader(io.StringIO(text)))
    else:
        raise ApiError(
            415, "unsupported_dataset_type", "数据集只支持 .json 与 .csv 文件。"
        )
    return [to_record(row) for row in rows]


def import_records(
    session,
    records: list[DatasetRecord],
    *,
    process_keywords: bool = True,
) -> AdapterResult:
    """把记录写入论文库，复用统一的校验、去重与关键词逻辑。"""
    result = AdapterResult(total=len(records))

    for record in records:
        if record.problems or not (record.conference and record.year):
            reason = "；".join(record.problems) or "缺少会议或年份，无法确定归属"
            result.skipped += 1
            result.failures.append((record.title, reason))
            continue
        try:
            paper, created = save_paper(
                session,
                title=record.title,
                conference=record.conference,
                year=record.year,
                abstract=record.abstract,
                author_keywords=record.keywords,
                landing_url=record.landing_url,
                pdf_url=record.pdf_url,
                primary_source=record.source,
                data_status="review",
                source_ref=(
                    (record.source, record.source_id) if record.source_id else None
                ),
                retrieved_at=record.retrieved_at,
            )
            if record.authors:
                paper.authors_json = json.dumps(record.authors, ensure_ascii=False)
                session.add(paper)
            if record.system_keywords:
                # 数据集若自带系统抽取结果，必须按「系统提取」写入，
                # 不能混进作者关键词——两类来源在统计口径上是分开的
                # 必须把作者关键词一起传进来：sync_* 是替换语义，
                # 传空列表会把刚刚写入的作者关键词删掉
                sync_paper_keywords(
                    session,
                    paper,
                    author_keywords=record.keywords,
                    system_keywords=record.system_keywords,
                )
                paper.keyword_status = "done"
                paper.keyword_ruleset_version = KEYWORD_RULESET_VERSION
                paper.keyword_processed_at = paper.keyword_processed_at or _now()
                session.add(paper)
            result.created += 1 if created else 0
            result.updated += 0 if created else 1
        except ApiError as error:
            result.skipped += 1
            result.failures.append((record.title, error.message))
        except Exception as error:  # noqa: BLE001 - 单条失败不中断整批
            result.skipped += 1
            result.failures.append((record.title, f"{type(error).__name__}: {error}"))

    if process_keywords:
        session.flush()
        process_pending(session)
    return result
