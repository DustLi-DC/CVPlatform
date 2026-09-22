"""应用配置与数据库路径解析。

设计依据：开发设计与验收.md 第 8.1、8.3 节。

数据库路径解析顺序（优先级从高到低）：
1. 环境变量 CVPLATFORM_DB_PATH 有值 → 直接使用（转绝对路径）
2. CVPLATFORM_ENV == "production"    → /var/lib/cvplatform/cvplatform.db
3. CVPLATFORM_ENV == "test"          → 系统临时目录下按进程唯一命名
4. 其他（开发默认）                   → <仓库根>/data/cvplatform.db

development 默认路径锚定仓库根（由本文件的 __file__ 逐级上溯得到），
不依赖启动时的工作目录，因此在任意目录启动服务都指向同一个数据库。
"""

from __future__ import annotations

import os
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

# 允许的三个会议，全项目共用这一处定义
CONFERENCES: tuple[str, ...] = ("CVPR", "ICCV", "ECCV")

# 数据状态与关键词处理状态的取值，与前端类型和多处校验共用
DATA_STATUSES: tuple[str, ...] = ("complete", "review", "failed")
ABSTRACT_STATUSES: tuple[str, ...] = ("present", "missing")
KEYWORD_STATUSES: tuple[str, ...] = ("pending", "running", "done", "failed")

# 关键词规则版本：规则、停用词或阈值变化时必须同步提升。
# kw-v2：修正单复数归一（不再把 across / analysis 这类词去掉尾部 s）
# kw-v3（阶段 7 依据 1200 篇真实样本校准）：
#   - 剔除链接与代码/出版样板词（原先 http github 是最高频短语）
#   - 补入学术行文与评价套话（demonstrate / existing 等实测占 30%~44%）
#   - 短语最小文档频次 20 → 5（原阈值下全语料只有 102 个短语可用）
#   - 支持 3d / 2d 这类数字开头的写法；同篇内被短语覆盖的通用裸词不再单列
# kw-v4（语料扩到 2020—2026 完整论文集、约 2.9 万篇后按规模重新校准）：
#   新增「大语料」档：min_df 5 → 20、短语阈值 5 → 50（固定阈值在 2.9 万篇上等于 0.017%，
#   候选词表会爆炸到 1.4 万词 / 6.5 万短语，长尾噪声占绝大多数）
KEYWORD_RULESET_VERSION = "kw-v4"
# 主题表版本：与 backend/app/data/topics_v1.json 内的「版本」字段保持一致
TOPIC_RULESET_VERSION = "topic-v3"

# 目标覆盖范围：阶段 1 确定的抽样组合（三大会议各两个实际举办年份）。
# 批量导入的标题匹配与真实数据采集都以这一处为准，避免两处范围不一致。
TARGET_CONFERENCE_YEARS: tuple[tuple[str, int], ...] = (
    ("CVPR", 2024),
    ("CVPR", 2025),
    ("ICCV", 2023),
    ("ICCV", 2025),
    ("ECCV", 2022),
    ("ECCV", 2024),
)

# 每个会议年份的抽样目标条数（阶段 1 确认为约 200）
HARVEST_SAMPLE_LIMIT = int(os.environ.get("HARVEST_SAMPLE_LIMIT") or 200)

# 完整论文集来源：HuggingFace 上的 ai-conferences/<CONF><YEAR> 数据集（阶段 11 起作为主来源）。
# 只纳入 min_year 之后的年份；纳入前抽样校验摘要覆盖率，未达阈值的年份跳过
# （会议尚未结束、数据仍在补齐的年份不应写进库里）。
DATASET_OWNER = "ai-conferences"
DATASET_MIN_YEAR = int(os.environ.get("DATASET_MIN_YEAR") or 2020)
DATASET_MIN_ABSTRACT_RATIO = float(os.environ.get("DATASET_MIN_ABSTRACT_RATIO") or 0.95)
# datasets-server 的 rows 接口单次最多 100 行
HF_PAGE_SIZE = 100

# 分析集合要求的最小标题长度（归一化后）
MIN_ANALYSIS_TITLE_LENGTH = 4
# 新增/编辑论文时要求的最小标题长度（与前端校验一致）
MIN_CREATE_TITLE_LENGTH = 8

# 列表分页上限
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 8

# 批量导入限制：行数与文件大小上限（阶段 1 与原型均按 500 行、2 MB 约定）
IMPORT_MAX_ROWS = int(os.environ.get("IMPORT_MAX_ROWS") or 500)
IMPORT_MAX_BYTES = int(os.environ.get("IMPORT_MAX_BYTES") or 2 * 1024 * 1024)

# 统计口径参数（阶段 7）
# 默认分组为「主题」（方案 A 已确认采用）。若将来改用方案 B（直接按关键词统计），
# 必须显式把这里改成 "keyword"：仅清空 topic 表是不够的，那样所有关键词都会落进「未归类」。
STATS_DEFAULT_GROUP_BY = os.environ.get("STATS_DEFAULT_GROUP_BY", "topic").strip().lower()
STATS_TOP_LIMIT = 10
STATS_TOP_LIMIT_MAX = 50
STATS_GRAPH_LIMIT = 40
STATS_GRAPH_MIN_EDGE = 2
# 进程内统计缓存条数上限（后端单 worker，超限时整体清空）
STATS_CACHE_MAX_ENTRIES = 64


def repository_root() -> Path:
    """仓库根目录：由本文件位置逐级上溯（backend/app/config.py → 仓库根）。"""
    return Path(__file__).resolve().parents[2]


def environment() -> str:
    """当前运行环境：development / test / production。"""
    value = os.environ.get("CVPLATFORM_ENV", "development").strip().lower()
    return value or "development"


# 测试环境的默认库路径按进程缓存一次。
# 若每次调用都生成新文件名，初始化与后续查询会落到两个不同的数据库文件上，
# 表现为“刚建好表却查不到数据”，因此同一次应用运行必须固定同一路径。
_test_database_path: Path | None = None


def _default_test_database_path() -> Path:
    global _test_database_path
    if _test_database_path is None:
        name = f"cvplatform-test-{os.getpid()}-{uuid.uuid4().hex[:8]}.db"
        _test_database_path = Path(tempfile.gettempdir()) / name
    return _test_database_path


def reset_path_cache() -> None:
    """清空缓存路径。测试在切换环境变量后调用，保证下一个用例拿到新路径。"""
    global _test_database_path
    _test_database_path = None


def resolve_database_path() -> Path:
    """按优先级解析数据库文件路径；只做解析，不创建目录。

    同一次进程运行内，相同的环境变量必然解析出相同路径。
    """
    explicit = os.environ.get("CVPLATFORM_DB_PATH", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()

    env = environment()
    if env == "production":
        return Path("/var/lib/cvplatform/cvplatform.db")
    if env == "test":
        return _default_test_database_path()
    return repository_root() / "data" / "cvplatform.db"


def sqlite_url(path: Path) -> str:
    """SQLModel/SQLAlchemy 使用的 SQLite URL。"""
    return f"sqlite:///{path.as_posix()}"


@dataclass(frozen=True)
class Settings:
    """运行期配置快照，供接口层读取。"""

    environment: str
    database_path: Path
    keyword_ruleset_version: str

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


def load_settings() -> Settings:
    return Settings(
        environment=environment(),
        database_path=resolve_database_path(),
        keyword_ruleset_version=KEYWORD_RULESET_VERSION,
    )
