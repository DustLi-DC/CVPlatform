"""完整论文集导入：把 HuggingFace 数据集写入论文库并记录来源与版本。

设计依据：阶段 11 起把「完整论文集」作为主数据来源，抽样爬取仅用于数据集未覆盖的会议年份。

- 复用 `services/adapters.py` 的清洗、校验、去重与保存逻辑，**不另起一套写入路径**；
- 每批提交一次，导入可中断、可重复执行：重复的论文按去重键识别为「更新」，不会产生副本；
- 每个数据集导入后在 meta 里记录 `dataset_import:<数据集>`（修订号、行数、时间、计数），
  统计覆盖接口据此把该会议年份标为「完整论文集」而不是「抽样」。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

from sqlmodel import Session

from ..models.entities import AppMeta
from .adapters import import_records, to_record
from .maintenance import mark_analysis_changed
from .sources import huggingface as hf

logger = logging.getLogger("cvplatform.dataset")

DATASET_META_PREFIX = "dataset_import:"


@dataclass
class DatasetImportSummary:
    """一个数据集的导入结果。"""

    dataset: str
    conference: str
    year: int
    rows: int
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)
    revision: str | None = None
    seconds: float = 0.0
    limit: int | None = None

    @property
    def label(self) -> str:
        return f"{self.conference} {self.year}"


def _set_meta(session: Session, key: str, value: str) -> None:
    row = session.get(AppMeta, key)
    if row is None:
        session.add(AppMeta(key=key, value=value))
        return
    row.value = value
    session.add(row)


def import_dataset(
    session: Session,
    ref: hf.DatasetRef,
    *,
    limit: int | None = None,
    batch_size: int = 200,
    on_progress=None,
) -> DatasetImportSummary:
    """导入一个会议论文集数据集。"""
    summary = DatasetImportSummary(
        dataset=ref.dataset,
        conference=ref.conference,
        year=ref.year,
        rows=ref.rows,
        limit=limit,
    )
    started = time.perf_counter()
    buffer: list = []

    def flush() -> None:
        if not buffer:
            return
        result = import_records(session, list(buffer), process_keywords=False)
        summary.created += result.created
        summary.updated += result.updated
        summary.skipped += result.skipped
        summary.failures.extend(result.failures[:5])
        buffer.clear()
        session.commit()

    for raw in hf.iter_records(ref, limit=limit, on_progress=on_progress):
        buffer.append(to_record(raw))
        if len(buffer) >= batch_size:
            flush()
    flush()

    summary.revision = hf.fetch_revision(ref.dataset)
    summary.seconds = round(time.perf_counter() - started, 1)
    _set_meta(
        session,
        f"{DATASET_META_PREFIX}{ref.dataset}",
        json.dumps(
            {
                "conference": ref.conference,
                "year": ref.year,
                "rows": ref.rows,
                "created": summary.created,
                "updated": summary.updated,
                "skipped": summary.skipped,
                "revision": summary.revision,
                "imported_at": hf._now(),
                "limit": limit,
            },
            ensure_ascii=False,
        ),
    )
    mark_analysis_changed(session)
    session.commit()
    logger.info(
        "数据集 %s 导入完成：新建 %d、更新 %d、跳过 %d，用时 %.1fs",
        ref.dataset,
        summary.created,
        summary.updated,
        summary.skipped,
        summary.seconds,
    )
    return summary


def imported_datasets(session: Session) -> dict[str, dict[str, object]]:
    """读取已导入的数据集记录：{数据集: 元信息}，供覆盖接口标注数据性质。"""
    rows = session.exec(
        AppMeta.__table__.select().where(AppMeta.key.like(f"{DATASET_META_PREFIX}%"))
    ).all()
    out: dict[str, dict[str, object]] = {}
    for row in rows:
        key = str(row[0])
        try:
            payload = json.loads(str(row[1]))
        except json.JSONDecodeError:
            continue
        out[key[len(DATASET_META_PREFIX) :]] = payload if isinstance(payload, dict) else {}
    return out
