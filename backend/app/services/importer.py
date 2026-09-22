"""批量导入的文件解析与校验。

设计依据：开发设计与验收.md 第 7.4 节，以及阶段 6 任务第 1、2 条。

支持两种格式：
- CSV：必须有 `title` 列，可选 `conference`、`year`；
- TXT：每行一个论文题目。

校验覆盖：扩展名与大小、行数上限、UTF-8 与 BOM、空行、行内重复、
CSV 引号与逗号转义、会议与年份取值。错误行保留原始行号与原因，
预览阶段只报告不写库，确认后才创建任务。
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from ..config import CONFERENCES, IMPORT_MAX_BYTES, IMPORT_MAX_ROWS

SUPPORTED_FORMATS = ("csv", "txt")
REQUIRED_COLUMNS = ("title",)
OPTIONAL_COLUMNS = ("conference", "year")


class ImportFileError(Exception):
    """文件本身不可用（类型、大小、编码、缺列），直接拒绝而不是逐行报错。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class PreviewRow:
    """预览中的一行：保留原始行号，便于使用者回到文件里核对。"""

    line_no: int
    title: str
    conference: str | None = None
    year: int | None = None
    status: str = "ok"
    message: str | None = None


@dataclass
class PreviewResult:
    file_format: str
    total_lines: int = 0
    valid_count: int = 0
    invalid_count: int = 0
    duplicate_in_file_count: int = 0
    blank_count: int = 0
    rows: list[PreviewRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def importable_count(self) -> int:
        return sum(1 for row in self.rows if row.status == "ok")


def detect_format(file_name: str) -> str:
    """按扩展名判断格式；不支持的类型直接拒绝。"""
    lowered = (file_name or "").strip().lower()
    for candidate in SUPPORTED_FORMATS:
        if lowered.endswith(f".{candidate}"):
            return candidate
    raise ImportFileError(
        "unsupported_file_type",
        "只支持 CSV 与 TXT 文件：CSV 需要包含 title 列，TXT 每行一个论文题目。",
    )


def decode_content(raw: bytes) -> str:
    """解码文件内容，处理 UTF-8 BOM 与常见编码问题。"""
    if not raw:
        raise ImportFileError("empty_file", "文件内容为空。")
    if len(raw) > IMPORT_MAX_BYTES:
        raise ImportFileError(
            "file_too_large",
            f"文件超过 {IMPORT_MAX_BYTES // 1024 // 1024} MB 上限，请拆分后再上传。",
        )
    # utf-8-sig 会吃掉 BOM；无法按 UTF-8 解码时给出明确提示而不是乱码
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("gb18030")
        except UnicodeDecodeError as error:
            raise ImportFileError(
                "unsupported_encoding",
                "无法按 UTF-8 或 GB18030 解码文件，请另存为 UTF-8 后重试。",
            ) from error
        return text


def _clean_field(value: str | None) -> str:
    return (value or "").strip().strip("\ufeff")


def _parse_year(value: str, line_no: int) -> tuple[int | None, str | None]:
    if not value:
        return None, None
    try:
        year = int(value)
    except ValueError:
        return None, f"第 {line_no} 行：year 必须是数字，收到 {value!r}。"
    if year <= 0 or year > 2100:
        return None, f"第 {line_no} 行：year 取值不合理（{year}）。"
    return year, None


def _parse_conference(value: str, line_no: int) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    upper = value.upper()
    if upper not in CONFERENCES:
        return None, f"第 {line_no} 行：conference 必须是 CVPR / ICCV / ECCV 之一，收到 {value!r}。"
    return upper, None


def parse_file(file_name: str, raw: bytes) -> PreviewResult:
    """解析文件并返回预览；不写数据库，也不访问网络。"""
    file_format = detect_format(file_name)
    text = decode_content(raw)

    if file_format == "csv":
        return _parse_csv(text)
    return _parse_txt(text)


def _parse_txt(text: str) -> PreviewResult:
    """TXT：每行一个题目；跳过空行，行内重复标为重复。"""
    result = PreviewResult(file_format="txt")
    seen: set[str] = set()
    for index, line in enumerate(text.splitlines(), start=1):
        result.total_lines += 1
        title = _clean_field(line)
        if not title:
            result.blank_count += 1
            continue
        if len(title) < 8:
            result.invalid_count += 1
            result.rows.append(
                PreviewRow(
                    line_no=index,
                    title=title,
                    status="invalid",
                    message="题目过短（少于 8 个字符），请填写完整题目。",
                )
            )
            continue
        key = title.casefold()
        if key in seen:
            result.duplicate_in_file_count += 1
            result.rows.append(
                PreviewRow(
                    line_no=index,
                    title=title,
                    status="duplicate_in_file",
                    message="文件内重复题目，导入时只处理第一次出现。",
                )
            )
            continue
        seen.add(key)
        result.valid_count += 1
        result.rows.append(PreviewRow(line_no=index, title=title))
    return _finalize(result)


def _parse_csv(text: str) -> PreviewResult:
    """CSV：必须有 title 列；使用标准 csv 解析以正确处理引号与逗号转义。"""
    result = PreviewResult(file_format="csv")
    reader = csv.DictReader(io.StringIO(text))
    headers = [(header or "").strip().lower() for header in (reader.fieldnames or [])]
    if not headers:
        raise ImportFileError("missing_header", "CSV 缺少表头行。")
    if "title" not in headers:
        raise ImportFileError(
            "missing_title_column",
            "CSV 必须包含 title 列（可选 conference、year）。",
        )
    unknown = [
        name for name in headers if name not in REQUIRED_COLUMNS + OPTIONAL_COLUMNS
    ]
    if unknown:
        result.warnings.append(
            f"以下列未被使用，将被忽略：{'、'.join(unknown)}。"
        )

    seen: set[str] = set()
    try:
        # 逐行迭代而不是先 list()：这样能读到 csv 记录的物理行号，
        # 空行与被跳过的不完整行都不会让行号错位
        for raw_row in reader:
            result.total_lines += 1
            line_no = reader.line_num
            _consume_csv_row(
                result, raw_row, line_no=line_no, seen=seen
            )
    except csv.Error as error:
        # 字段超过 csv 模块上限、引号不匹配等都会在这里抛出，
        # 必须转成清楚的校验错误，不能让它冒泡成 500
        raise ImportFileError(
            "invalid_csv",
            f"CSV 解析失败：{error}。请检查是否存在未闭合的引号或过长的字段"
            f"（单字段上限 {csv.field_size_limit()} 字节）。",
        ) from error
    return _finalize(result)


def _consume_csv_row(
    result: PreviewResult,
    raw_row: dict,
    *,
    line_no: int,
    seen: set[str],
) -> None:
    """处理 CSV 的一行数据；行号由调用方从 csv 读取，保证是文件里的物理行号。"""
    row = {
        (key or "").strip().lower(): value for key, value in raw_row.items() if key
    }
    title = _clean_field(row.get("title"))
    if not title:
        result.blank_count += 1
        return

    problems: list[str] = []
    if len(title) < 8:
        problems.append("题目过短（少于 8 个字符）。")
    conference, conference_error = _parse_conference(
        _clean_field(row.get("conference")), line_no
    )
    if conference_error:
        problems.append(conference_error)
    year, year_error = _parse_year(_clean_field(row.get("year")), line_no)
    if year_error:
        problems.append(year_error)

    if problems:
        result.invalid_count += 1
        result.rows.append(
            PreviewRow(
                line_no=line_no,
                title=title,
                conference=conference,
                year=year,
                status="invalid",
                message="；".join(problems),
            )
        )
        return

    # 文件内去重也带会议年份：只有「同一会议年份 + 同一题目」才算重复，
    # 同一题目出现在两个会议年份是两条独立记录
    key = f"{conference or ''}|{year or ''}|{title.casefold()}"
    if key in seen:
        result.duplicate_in_file_count += 1
        result.rows.append(
            PreviewRow(
                line_no=line_no,
                title=title,
                conference=conference,
                year=year,
                status="duplicate_in_file",
                message="文件内同一会议年份出现重复题目，导入时只处理第一次出现。",
            )
        )
        return
    seen.add(key)
    result.valid_count += 1
    result.rows.append(
        PreviewRow(line_no=line_no, title=title, conference=conference, year=year)
    )


def _finalize(result: PreviewResult) -> PreviewResult:
    """统一做行数上限校验；超出时给出明确提示。"""
    if result.total_lines > IMPORT_MAX_ROWS:
        raise ImportFileError(
            "too_many_rows",
            f"文件共 {result.total_lines} 行，超过单次 {IMPORT_MAX_ROWS} 行上限，请拆分后再上传。",
        )
    if result.valid_count == 0 and result.invalid_count == 0:
        raise ImportFileError("no_data_rows", "文件里没有可导入的数据行。")
    return result


# 供前端展示的模板与字段说明，和解析实现放在一起，避免两处口径不一致
TEMPLATE_TXT = """High-Resolution Image Synthesis with Latent Diffusion Models
VideoMAE V2: Scaling Video Masked Autoencoders with Dual Masking
Zip-NeRF: Anti-Aliased Grid-Based Neural Radiance Fields"""

TEMPLATE_CSV = """title,conference,year
DETRs Beat YOLOs on Real-time Object Detection,CVPR,2024
Segment Anything,ICCV,2023"""

FIELD_NOTES: tuple[dict[str, str], ...] = (
    {"name": "title", "required": "必填", "note": "论文完整题目，建议使用会议论文页原文"},
    {
        "name": "conference",
        "required": "选填",
        "note": "只能填 CVPR / ICCV / ECCV，留空时按题目在会议索引中匹配",
    },
    {"name": "year", "required": "选填", "note": "目标年份区间内的年份，留空时按索引匹配结果确定"},
)
