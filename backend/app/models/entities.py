"""数据库实体定义（SQLModel）。

字段与约束依据 开发设计与验收.md 第 3 章。表结构由 db/migrations.py 以显式 DDL 创建；
本模块只用于查询与写入，不负责建表，避免“模型即建表”在多版本迁移下产生结构漂移。
tests/test_schema.py 会校验模型字段与数据库实际列一致。
"""

from __future__ import annotations

from sqlmodel import Field, SQLModel


class Paper(SQLModel, table=True):
    """论文。对外一律用 id 作为稳定标识；code 是展示编号，创建时分配且不复用。"""

    __tablename__ = "paper"

    id: int | None = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)
    code_origin_conference: str
    code_origin_year: int
    dedup_key: str = Field(index=True, unique=True)
    title: str
    title_normalized: str = Field(index=True)
    conference: str = Field(index=True)
    year: int = Field(index=True)
    abstract: str | None = None
    abstract_status: str = "missing"
    authors_json: str | None = None
    keywords_source_json: str | None = None
    landing_url: str | None = None
    pdf_url: str | None = None
    primary_source: str = "manual"
    data_status: str = Field(default="review", index=True)
    keyword_status: str = Field(default="pending", index=True)
    keyword_ruleset_version: str | None = None
    keyword_processed_at: str | None = None
    retrieved_at: str | None = None
    created_at: str
    updated_at: str


class PaperSource(SQLModel, table=True):
    """论文的来源标识，一篇论文可挂多个来源，用于跨来源去重。"""

    __tablename__ = "paper_source"

    id: int | None = Field(default=None, primary_key=True)
    paper_id: int = Field(foreign_key="paper.id", index=True)
    source: str
    source_id: str
    url: str | None = None
    retrieved_at: str | None = None


class Keyword(SQLModel, table=True):
    """关键词。同一归一形式在作者关键词与系统提取下各占一行，故唯一约束只放在组合上。"""

    __tablename__ = "keyword"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    name_normalized: str = Field(index=True)
    language: str = "en"
    origin: str = Field(index=True)
    topic_id: int | None = Field(default=None, foreign_key="topic.id")
    doc_freq: int = 0
    created_at: str


class PaperKeyword(SQLModel, table=True):
    """论文—关键词关系。版本参与唯一键，便于保留历史版本按版本过滤统计。"""

    __tablename__ = "paper_keyword"

    id: int | None = Field(default=None, primary_key=True)
    paper_id: int = Field(foreign_key="paper.id", index=True)
    keyword_id: int = Field(foreign_key="keyword.id", index=True)
    tfidf_score: float | None = None
    textrank_score: float | None = None
    rank: int | None = None
    ruleset_version: str = Field(index=True)
    created_at: str


class Topic(SQLModel, table=True):
    """主题（归并层）。主题初值由真实数据产出后写入版本化配置文件。"""

    __tablename__ = "topic"

    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(unique=True, index=True)
    name: str
    group_name: str | None = None
    is_active: bool = True
    sort_order: int = 0
    created_at: str


class TopicAlias(SQLModel, table=True):
    """主题别名：把同义表达归并到同一主题，不改写原始关键词。"""

    __tablename__ = "topic_alias"

    id: int | None = Field(default=None, primary_key=True)
    topic_id: int = Field(foreign_key="topic.id", index=True)
    alias_normalized: str = Field(unique=True, index=True)


class CollectionTask(SQLModel, table=True):
    """采集任务（批量导入与抽取式采集共用）。"""

    __tablename__ = "collection_task"

    id: int | None = Field(default=None, primary_key=True)
    kind: str = "batch"
    file_name: str | None = None
    file_size: int | None = None
    file_format: str | None = None
    sample_stride: int | None = None
    sample_limit: int | None = None
    total_count: int = 0
    pending_count: int = 0
    running_count: int = 0
    success_count: int = 0
    duplicate_count: int = 0
    failed_count: int = 0
    status: str = Field(default="pending", index=True)
    message: str | None = None
    ruleset_version: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


class CollectionTaskItem(SQLModel, table=True):
    """任务明细。中断点由明细状态决定，续跑按明细恢复。"""

    __tablename__ = "collection_task_item"

    id: int | None = Field(default=None, primary_key=True)
    task_id: int = Field(foreign_key="collection_task.id", index=True)
    line_no: int
    input_title: str
    input_conference: str | None = None
    input_year: int | None = None
    status: str = Field(default="pending", index=True)
    paper_id: int | None = Field(default=None, foreign_key="paper.id")
    duplicate_of_paper_id: int | None = Field(default=None, foreign_key="paper.id")
    message: str | None = None
    attempts: int = 0
    created_at: str
    updated_at: str


class AppMeta(SQLModel, table=True):
    """键值配置与运行状态。"""

    __tablename__ = "meta"

    key: str = Field(primary_key=True)
    value: str


class ConferenceYearSeq(SQLModel, table=True):
    """编号序列：按会议年份独立递增，只增不减，删除论文不回收序号。"""

    __tablename__ = "conference_year_seq"

    conference: str = Field(primary_key=True)
    year: int = Field(primary_key=True)
    next_seq: int = 1


class IdfTerm(SQLModel, table=True):
    """IDF 缓存。统计请求直接读取，不在请求中重新拟合。"""

    __tablename__ = "idf_term"

    id: int | None = Field(default=None, primary_key=True)
    term_normalized: str = Field(index=True)
    df: int
    idf: float
    ruleset_version: str = Field(index=True)
    corpus_size: int
