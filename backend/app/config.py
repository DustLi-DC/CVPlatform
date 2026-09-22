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
KEYWORD_RULESET_VERSION = "kw-v2"
TOPIC_RULESET_VERSION = "topic-v0"

# 分析集合要求的最小标题长度（归一化后）
MIN_ANALYSIS_TITLE_LENGTH = 4
# 新增/编辑论文时要求的最小标题长度（与前端校验一致）
MIN_CREATE_TITLE_LENGTH = 8

# 列表分页上限
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 8


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
