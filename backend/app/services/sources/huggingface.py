"""HuggingFace 会议论文集数据集来源（`ai-conferences/{CONF}{YEAR}`）。

用途：作为**完整论文集**的数据来源，替代按索引等距抽样爬取。单个数据集的内容就是该届会议的
全部录用论文，字段含 title / abstract / authors / cvf_url（ECCV 为 ecva_url）/ pdf_url /
paper_id（另有 bibtex、doi、arxiv_id、supp_url 等，本平台暂不入库）。

设计要点：

- **优先下载 parquet 文件**（每届会议一个文件，约 1–4 MB，走 HuggingFace Hub 的下载配额），
  用 pyarrow 解析；pyarrow 是**开发期可选依赖**（列在 requirements-dev.txt），
  未安装时自动回落到 datasets-server 的 JSON 分页接口（每页 100 行，无需任何额外依赖）。
  这样既能避免 rows 接口的严格限额，又不会让生产运行环境背上额外依赖。
- **纳入前先校验完整度**：抽样若干行检查摘要覆盖率，未达阈值的年份（例如会议尚未结束、
  数据仍在补齐）跳过并记录原因，而不是把半成品写进库里。
- 记录数据集的 HF 仓库修订号（sha），使「这批数据来自哪个版本」可复现。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from ...config import (
    CONFERENCES,
    DATASET_MIN_ABSTRACT_RATIO,
    DATASET_MIN_YEAR,
    DATASET_OWNER,
    HF_PAGE_SIZE,
)
from .http import SourceUnavailable, fetch_bytes, fetch_json

logger = logging.getLogger("cvplatform.sources")

SOURCE_NAME = "huggingface"
INFO_URL = "https://datasets-server.huggingface.co/info?dataset={dataset}"
ROWS_URL = (
    "https://datasets-server.huggingface.co/rows"
    "?dataset={dataset}&config=default&split=train&offset={offset}&length={length}"
)
API_URL = "https://huggingface.co/api/datasets/{dataset}"
TREE_URL = "https://huggingface.co/api/datasets/{dataset}/tree/main/data"
# 只取用到的文本列：parquet 里还有 bibtex（体积最大）等本平台不入库的字段
_TEXT_COLUMNS = (
    "paper_id",
    "title",
    "authors",
    "cvf_url",
    "ecva_url",
    "pdf_url",
    "abstract",
)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class DatasetRef:
    """一个可用的会议论文集数据集。"""

    dataset: str
    conference: str
    year: int
    rows: int
    revision: str | None = None
    abstract_ratio: float | None = None

    @property
    def url(self) -> str:
        return f"https://huggingface.co/datasets/{self.dataset}"

    @property
    def label(self) -> str:
        return f"{self.conference} {self.year}（{self.rows} 篇）"


def dataset_id(conference: str, year: int) -> str:
    return f"{DATASET_OWNER}/{conference}{year}"


def _as_dataset_ref(payload: object, conference: str, year: int) -> DatasetRef | None:
    """从 datasets-server 的 info 响应解析出数据集信息；结构不符时返回 None。"""
    if not isinstance(payload, dict):
        return None
    info = payload.get("dataset_info")
    if not isinstance(info, dict):
        return None
    body = info.get("default")
    if not isinstance(body, dict):
        return None
    splits = body.get("splits")
    if not isinstance(splits, dict):
        return None
    train = splits.get("train")
    rows = train.get("num_examples") if isinstance(train, dict) else None
    if not isinstance(rows, int) or rows <= 0:
        return None
    features = body.get("features")
    if not isinstance(features, dict) or "title" not in features:
        return None
    return DatasetRef(
        dataset=dataset_id(conference, year),
        conference=conference,
        year=year,
        rows=rows,
    )


# HuggingFace 对未收录/无权限的数据集返回 401（而不是 404），因此这两类状态都按「没有该数据集」处理
_ABSENT_STATUSES = (401, 403, 404)


def probe(conference: str, year: int, *, timeout: float | None = None) -> DatasetRef | None:
    """探测某会议年份是否有数据集；未收录（401/403/404）返回 None，其余错误照常抛出。"""
    dataset = dataset_id(conference, year)
    try:
        payload = fetch_json(
            INFO_URL.format(dataset=dataset), source=SOURCE_NAME, timeout=timeout
        )
    except SourceUnavailable as error:
        # 未收录该年份是正常情况（例如 ICCV 偶数年没有会议），不当作故障
        if error.status in _ABSENT_STATUSES:
            logger.debug("数据集未收录：%s（HTTP %s）", dataset, error.status)
            return None
        raise
    ref = _as_dataset_ref(payload, conference, year)
    if ref is not None:
        return ref
    # info 结构异常时用文件树兜底判断「是否存在」；行数留待读取 parquet 时确定
    try:
        urls = parquet_urls(DatasetRef(dataset, conference, year, rows=0), timeout=timeout)
    except Exception:  # noqa: BLE001
        return None
    if not urls:
        return None
    return DatasetRef(dataset=dataset, conference=conference, year=year, rows=0)


def parquet_urls(ref: DatasetRef, *, timeout: float | None = None) -> list[str]:
    """列出数据集的 parquet 下载地址（走 Hub 的文件树接口，与 datasets-server 配额分离）。"""
    payload = fetch_json(
        TREE_URL.format(dataset=ref.dataset), source=SOURCE_NAME, timeout=timeout
    )
    if not isinstance(payload, list):
        return []
    urls: list[str] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        if path.endswith(".parquet"):
            urls.append(f"https://huggingface.co/datasets/{ref.dataset}/resolve/main/{path}")
    return urls


def parquet_available() -> bool:
    """pyarrow 是否可用（不可用时回落到 JSON 分页）。"""
    try:
        import pyarrow.parquet  # noqa: F401
    except ImportError:
        return False
    return True


def _parquet_rows(ref: DatasetRef, *, limit: int | None = None, timeout: float | None = None):
    """从 parquet 文件逐批产出原始行；未安装 pyarrow 时抛出 ImportError 由调用方回落。"""
    import io

    import pyarrow.parquet as pq

    produced = 0
    for url in parquet_urls(ref, timeout=timeout):
        body = fetch_bytes(url, source=SOURCE_NAME, timeout=timeout)
        parquet_file = pq.ParquetFile(io.BytesIO(body))
        for batch in parquet_file.iter_batches(batch_size=500, columns=_TEXT_COLUMNS):
            for row in batch.to_pylist():
                if limit is not None and produced >= limit:
                    return
                yield row
                produced += 1


def fetch_revision(dataset: str, *, timeout: float | None = None) -> str | None:
    """取数据集仓库的修订号（sha）；失败只记日志，不影响导入。"""
    try:
        payload = fetch_json(
            API_URL.format(dataset=dataset), source=SOURCE_NAME, timeout=timeout
        )
    except Exception as error:  # noqa: BLE001 - 修订号取不到不应中断导入
        logger.warning("取数据集修订号失败：%s（%s）", dataset, error)
        return None
    sha = payload.get("sha") if isinstance(payload, dict) else None
    return str(sha) if sha else None


def fetch_page(
    ref: DatasetRef,
    offset: int,
    *,
    length: int = HF_PAGE_SIZE,
    timeout: float | None = None,
) -> tuple[list[dict], int]:
    """取一页原始行，返回 (行列表, 总行数)。"""
    payload = fetch_json(
        ROWS_URL.format(dataset=ref.dataset, offset=offset, length=length),
        source=SOURCE_NAME,
        timeout=timeout,
    )
    if not isinstance(payload, dict):
        raise SourceUnavailable(SOURCE_NAME, "数据集返回的内容不是预期结构")
    raw_rows = payload.get("rows")
    if not isinstance(raw_rows, list):
        raise SourceUnavailable(SOURCE_NAME, "数据集返回的内容缺少 rows 字段")
    total = payload.get("num_rows_total")
    rows = [item.get("row") for item in raw_rows if isinstance(item, dict)]
    return [row for row in rows if isinstance(row, dict)], int(total or 0)


def abstract_ratio(ref: DatasetRef, *, sample: int = 100, timeout: float | None = None) -> float:
    """摘要覆盖率，用于判断数据集是否可以纳入。

    有 parquet 可读时按**全部行**精确统计（更可靠，也不消耗 rows 接口配额）；
    否则抽样估算。
    """
    if parquet_available():
        try:
            total = filled = 0
            for row in _parquet_rows(ref, timeout=timeout):
                total += 1
                if str(row.get("abstract") or "").strip():
                    filled += 1
            return filled / total if total else 0.0
        except Exception as error:  # noqa: BLE001 - 回落抽样
            logger.warning("按 parquet 统计摘要覆盖率失败，改用抽样：%s（%s）", ref.dataset, error)
    rows, _total = fetch_page(ref, 0, length=min(sample, HF_PAGE_SIZE), timeout=timeout)
    if not rows:
        return 0.0
    filled = sum(1 for row in rows if str(row.get("abstract") or "").strip())
    return filled / len(rows)


def discover(
    *,
    conferences: tuple[str, ...] = CONFERENCES,
    min_year: int = DATASET_MIN_YEAR,
    max_year: int | None = None,
    verify: bool = True,
    min_abstract_ratio: float = DATASET_MIN_ABSTRACT_RATIO,
    timeout: float | None = None,
    on_note=None,
    skipped_out: list[DatasetRef] | None = None,
) -> list[DatasetRef]:
    """发现可用数据集；verify=True 时逐个校验摘要完整度，不达标的跳过。

    `on_note(text)` 用于把「探测到但跳过」的原因回传给调用方（命令行打印）。
    """
    import datetime as _datetime

    upper = max_year if max_year is not None else _datetime.datetime.now(UTC).year + 1
    found: list[DatasetRef] = []
    for conference in conferences:
        for year in range(min_year, upper + 1):
            try:
                ref = probe(conference, year, timeout=timeout)
            except Exception as error:  # noqa: BLE001 - 单个组合失败不影响其余
                if on_note is not None:
                    on_note(f"{conference} {year} 探测失败：{error}")
                continue
            if ref is None:
                continue
            if verify:
                try:
                    ratio = abstract_ratio(ref, timeout=timeout)
                except Exception as error:  # noqa: BLE001
                    if on_note is not None:
                        on_note(f"{ref.label} 完整度校验失败：{error}")
                    continue
                if ratio < min_abstract_ratio:
                    if on_note is not None:
                        on_note(
                            f"{ref.label} 跳过：摘要覆盖率 {ratio:.0%} < {min_abstract_ratio:.0%}"
                            "（会议数据仍在补齐）"
                        )
                    if skipped_out is not None:
                        skipped_out.append(
                            DatasetRef(
                                dataset=ref.dataset,
                                conference=ref.conference,
                                year=ref.year,
                                rows=ref.rows,
                                abstract_ratio=ratio,
                            )
                        )
                    continue
                ref = DatasetRef(
                    dataset=ref.dataset,
                    conference=ref.conference,
                    year=ref.year,
                    rows=ref.rows,
                    abstract_ratio=ratio,
                )
            found.append(ref)
    return found


def iter_records(
    ref: DatasetRef,
    *,
    limit: int | None = None,
    timeout: float | None = None,
    on_progress=None,
):
    """逐条产出可直接交给 adapters.to_record 的字典。

    只做字段搬运与归一，不做校验：标题为空的行由适配层按「缺少标题」跳过并计数。
    """
    if parquet_available():
        try:
            produced = 0
            for row in _parquet_rows(ref, limit=limit, timeout=timeout):
                yield _normalize(row, ref)
                produced += 1
                if on_progress is not None and produced % 500 == 0:
                    on_progress(produced, ref.rows)
            if on_progress is not None:
                on_progress(produced, ref.rows)
            logger.info("数据集 %s 读取完成（parquet）：%d 行", ref.dataset, produced)
            return
        except Exception as error:  # noqa: BLE001 - 回落 JSON 分页
            logger.warning("parquet 读取失败，回落到 JSON 分页：%s（%s）", ref.dataset, error)

    offset = 0
    produced = 0
    fetched = 0
    total = ref.rows
    while True:
        length = HF_PAGE_SIZE
        if limit is not None:
            remaining = limit - produced
            if remaining <= 0:
                break
            length = min(length, remaining)
        rows, reported_total = fetch_page(ref, offset, length=length, timeout=timeout)
        if reported_total:
            total = reported_total
        if not rows:
            break
        fetched += len(rows)
        for row in rows:
            if limit is not None and produced >= limit:
                break
            yield _normalize(row, ref)
            produced += 1
        if on_progress is not None:
            on_progress(produced, total)
        offset += len(rows)
        if offset >= total:
            break
    logger.info("数据集 %s 读取完成：%d 行", ref.dataset, produced)


def _normalize(row: dict, ref: DatasetRef) -> dict:
    """把数据集行映射为适配层的字段形状（别名见 adapters.FIELD_ALIASES）。"""
    landing = str(row.get("cvf_url") or row.get("ecva_url") or "").strip()
    pdf = str(row.get("pdf_url") or "").strip()
    paper_id = str(row.get("paper_id") or "").strip()
    authors = row.get("authors")
    if not isinstance(authors, list):
        authors = []
    return {
        "title": str(row.get("title") or "").strip(),
        "abstract": str(row.get("abstract") or "").strip() or None,
        "authors": [str(item).strip() for item in authors if str(item).strip()],
        "conference": ref.conference,
        "year": ref.year,
        "landing_url": landing or None,
        "pdf_url": pdf or None,
        # 来源标识写明「哪个数据集 + 数据集内的 id」，便于逐条回溯
        "source": SOURCE_NAME,
        "source_id": f"{ref.dataset}#{paper_id}" if paper_id else None,
        "retrieved_at": _now(),
    }
