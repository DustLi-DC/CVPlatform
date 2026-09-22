"""关键词与主题的维护接口（按需处理待处理或待重算的论文）。

设计依据：开发设计与验收.md 第 4.4、5.5 节。

统计请求本身**从不**抽词或拟合语料，只读已存的关系；
需要补齐或重算时由这里的接口显式触发，调用方能看到真实的数量与耗时，
而不是在统计接口里隐式产生副作用。
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Query

from ..db.engine import session_scope
from ..services import keyword_job, stats, topic_layer

logger = logging.getLogger("cvplatform.keywords")

router = APIRouter(prefix="/api/keywords", tags=["keywords"])


@router.get("/status")
def get_status() -> dict[str, object]:
    """关键词处理现状：分母、语料、各状态数量、待处理量与主题映射覆盖。"""
    with session_scope() as session:
        counts = keyword_job.status_counts(session)
        return {
            "analysis_papers": counts["analysis_papers"],
            "corpus_papers": counts["corpus_papers"],
            "by_status": counts["by_status"],
            "pending_or_stale": counts["pending_or_stale"],
            "ruleset_version": counts["ruleset_version"],
            "system_keywords": counts["system_keywords"],
            "mapped_keywords": counts["mapped_keywords"],
        }


@router.post("/process")
def post_process(
    limit: int | None = Query(None, ge=1, description="本次最多处理多少篇"),
    force: bool = Query(False, description="忽略状态与版本，对语料全量重算"),
) -> dict[str, object]:
    """按需处理待处理、失败或版本过期的论文。

    处理完成后分析集合版本自增，统计缓存随之失效——下一次统计请求会拿到新结果，
    不需要调用方手动清缓存。
    """
    started = time.perf_counter()
    with session_scope() as session:
        summary = keyword_job.process_pending(session, limit=limit, force=force)
    elapsed = time.perf_counter() - started
    stats.clear_cache()
    return {
        "corpus_size": summary.corpus_size,
        "processed": summary.processed,
        "empty": summary.empty,
        "failed": summary.failed,
        "remaining": summary.remaining,
        "effective_min_df": summary.effective_min_df,
        "phrases_enabled": summary.phrases_enabled,
        "config_signature": summary.config_signature,
        "elapsed_seconds": round(elapsed, 2),
    }


@router.post("/topics/reload")
def post_reload_topics() -> dict[str, object]:
    """重新载入主题表并重算关键词的主题映射（主题表文件更新后调用）。"""
    with session_scope() as session:
        result = topic_layer.sync_topics(session)
    stats.clear_cache()
    return result
