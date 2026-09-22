"""会议年份索引缓存：标题 → 会议年份的权威匹配。

标题列表（TXT 每行一个题目）本身不含会议与年份，而论文记录要求会议年份有效，
因此在批量导入与真实数据采集里都需要先确定「这条标题属于哪个会议哪一年」。

做法是把目标会议年份的索引页取回来并缓存（每个组合一次请求），
之后所有标题匹配都在内存里完成，不再逐条访问网络。
CVF 收录 CVPR/ICCV、ECVA 收录 ECCV，两者都给出权威的会议年份归属。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from ..config import TARGET_CONFERENCE_YEARS
from .papers import normalize_title
from .sources import cvf, ecva
from .sources.openalex import token_set_similarity

# 标题匹配的最低相似度：低于此值视为没找到，宁可报未匹配也不猜
MATCH_THRESHOLD = 0.86


@dataclass(frozen=True)
class IndexedPaper:
    """索引里的一条记录：标题、会议年份与详情页路径。"""

    title: str
    conference: str
    year: int
    paper_path: str
    landing_url: str

    @property
    def source(self) -> str:
        return ecva.SOURCE_NAME if self.conference == "ECCV" else cvf.SOURCE_NAME


class IndexCache:
    """按会议年份缓存索引，并支持标题匹配。

    线程安全：批量任务在处理线程里使用，接口层可能同时查询状态。
    """

    def __init__(self, *, match_threshold: float = MATCH_THRESHOLD) -> None:
        self._lock = threading.Lock()
        self._entries: dict[tuple[str, int], list[IndexedPaper]] = {}
        self._by_normalized: dict[tuple[str, int], dict[str, IndexedPaper]] = {}
        self.match_threshold = match_threshold

    def load(
        self, conference: str, year: int, *, timeout: float | None = None
    ) -> list[IndexedPaper]:
        """载入某会议年份的索引（已缓存则直接返回）。"""
        key = (conference, year)
        with self._lock:
            cached = self._entries.get(key)
        if cached is not None:
            return cached

        if conference == "ECCV":
            raw = ecva.fetch_index(year, timeout=timeout)
            entries = [
                IndexedPaper(
                    title=item.title,
                    conference=conference,
                    year=item.year or year,
                    paper_path=item.paper_path,
                    landing_url=item.landing_url,
                )
                for item in raw
            ]
        else:
            raw = cvf.fetch_index(conference, year, timeout=timeout)
            entries = [
                IndexedPaper(
                    title=item.title,
                    conference=conference,
                    year=year,
                    paper_path=item.paper_path,
                    landing_url=item.landing_url,
                )
                for item in raw
            ]

        index = {normalize_title(item.title): item for item in entries}
        with self._lock:
            self._entries[key] = entries
            self._by_normalized[key] = index
        return entries

    def load_all(
        self,
        *,
        timeout: float | None = None,
        on_progress=None,
    ) -> dict[tuple[str, int], list[IndexedPaper]]:
        """载入全部目标组合。单个组合失败时跳过并继续，不让一处失败拖垮整批。"""
        loaded: dict[tuple[str, int], list[IndexedPaper]] = {}
        for conference, year in TARGET_CONFERENCE_YEARS:
            try:
                loaded[(conference, year)] = self.load(
                    conference, year, timeout=timeout
                )
            except Exception as error:  # noqa: BLE001 - 记录后继续下一个组合
                if on_progress is not None:
                    on_progress(conference, year, error)
        return loaded

    def cached_keys(self) -> list[tuple[str, int]]:
        with self._lock:
            return self._keys_locked()

    def _keys_locked(self) -> list[tuple[str, int]]:
        """已持有锁时的内部访问；threading.Lock 不可重入，
        在持锁状态下再调用 cached_keys() 会直接死锁。"""
        return sorted(self._entries)

    def match(
        self, title: str, *, conference: str | None = None, year: int | None = None
    ) -> tuple[IndexedPaper | None, float]:
        """按标题匹配，返回 (命中的条目, 相似度)。

        先做归一化标题全等匹配（快且准），再对已缓存的组合做相似度匹配。
        指定会议年份时只在该组合内查找。
        """
        normalized = normalize_title(title)
        if not normalized:
            return None, 0.0

        with self._lock:
            if conference and year:
                # 明确指定了会议年份：**只在该组合内查找**。
                # 该组合索引未载入时返回未命中，由调用方按失败处理；
                # 绝不能退回「遍历所有已缓存组合」，否则会把其他会议年份的条目
                # 匹配给指定年份（实测出现过指定 ICCV 2025 却返回 CVPR 2024 条目）。
                keys = [(conference, year)] if (conference, year) in self._entries else []
            else:
                keys = self._keys_locked()
            index_snapshot = {
                key: (self._entries[key], self._by_normalized.get(key, {}))
                for key in keys
            }

        for key, (_, index) in index_snapshot.items():
            hit = index.get(normalized)
            if hit is not None:
                return hit, 1.0

        best: IndexedPaper | None = None
        best_score = 0.0
        for _, (entries, _) in index_snapshot.items():
            for entry in entries:
                score = token_set_similarity(title, entry.title)
                if score > best_score:
                    best, best_score = entry, score
        if best_score >= self.match_threshold:
            return best, best_score
        return None, best_score


# 进程内共享的索引缓存：批量任务与采集编排复用，避免重复抓取大索引页
shared_cache = IndexCache()
