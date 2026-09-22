"""论文服务层：编号分配、去重判定、CRUD、检索与关联清理。

设计依据：开发设计与验收.md 第 3.2、3.3、3.4、7.2 节。

所有写入都经过同一套保存逻辑（normalize → dedup → 编号 → 关键词关联），
采集、批量导入与手工新增复用这些函数，不在接口层重复实现。
"""

from __future__ import annotations

import json
import unicodedata
from datetime import UTC, datetime

from sqlalchemy import func, or_, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from ..config import (
    CONFERENCES,
    DATA_STATUSES,
    DEFAULT_PAGE_SIZE,
    KEYWORD_STATUSES,
    MAX_PAGE_SIZE,
    MIN_ANALYSIS_TITLE_LENGTH,
    MIN_CREATE_TITLE_LENGTH,
)
from ..models.entities import (
    Keyword,
    Paper,
    PaperKeyword,
    PaperSource,
)
from .keywords import (
    clear_system_keywords,
    current_ruleset_version,
    dump_keywords_json,
    normalize_keyword,
    sync_paper_keywords,
)

SORT_FIELDS = ("code", "title", "year", "conference", "created_at")


class ApiError(Exception):
    """业务错误：由接口层转换为统一错误响应。"""

    def __init__(
        self, status_code: int, code: str, message: str, **extra: object
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.extra = extra


class DuplicatePaperError(ApiError):
    """去重键冲突，附带已存在的论文摘要。"""

    def __init__(self, existing: Paper) -> None:
        super().__init__(
            409,
            "duplicate_paper",
            "该论文已存在：会议、年份与题目相同的记录不允许重复入库。",
            existing={
                "id": existing.id,
                "code": existing.code,
                "title": existing.title,
                "conference": existing.conference,
                "year": existing.year,
            },
        )
        self.existing = existing


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_title(title: str) -> str:
    """归一化标题：只消除大小写、标点、空白与全半角差异，不做词形还原。

    刻意保守，避免把不同论文并成同一条记录。
    """
    text = unicodedata.normalize("NFKC", title).strip().lower()
    # 保留字母（含非拉丁字母）与数字，其余字符折叠为单空格
    cleaned = "".join(char if char.isalnum() else " " for char in text)
    return " ".join(cleaned.split())


def build_dedup_key(conference: str, year: int, title: str) -> str:
    """去重键：会议 + 年份 + 归一化标题。"""
    return f"{conference}|{year}|{normalize_title(title)}"


def derive_display_status(paper: Paper) -> str:
    """展示徽标，优先级：failed → review → abstract_missing → complete。

    由服务端计算并下发，前端不重复实现优先级逻辑。
    """
    if paper.data_status == "failed" or paper.keyword_status == "failed":
        return "failed"
    if paper.data_status == "review":
        return "review"
    if paper.abstract_status == "missing":
        return "abstract_missing"
    return "complete"


def code_scope_mismatch(paper: Paper) -> bool:
    """编号分配时的会议年份与当前值是否已不一致。"""
    return (
        paper.code_origin_conference != paper.conference
        or paper.code_origin_year != paper.year
    )


def code_note(paper: Paper) -> str | None:
    if not code_scope_mismatch(paper):
        return None
    return "编号为入库时分配，与当前会议年份不一致"


def allocate_code(session: Session, conference: str, year: int) -> str:
    """原子分配编号：{会议}-{年份}-{4 位序号}，只增不减、永不复用。

    先 INSERT OR IGNORE 确保序列行存在，再用一条 UPDATE … RETURNING 递增并取号。
    读与写在同一条语句内完成，因此两个并发请求不可能拿到同一个序号。
    这里不能用“先 get 再赋值”的写法：FastAPI 的同步接口在线程池中执行，
    单 worker 并不等于请求串行，先读后写会撞上 UNIQUE(code) 并返回 500。
    """
    session.execute(
        text(
            "INSERT OR IGNORE INTO conference_year_seq (conference, year, next_seq) "
            "VALUES (:conference, :year, 1)"
        ),
        {"conference": conference, "year": year},
    )
    row = session.execute(
        text(
            "UPDATE conference_year_seq SET next_seq = next_seq + 1 "
            "WHERE conference = :conference AND year = :year "
            "RETURNING next_seq - 1"
        ),
        {"conference": conference, "year": year},
    ).one()
    return f"{conference}-{year}-{int(row[0]):04d}"


def validate_title(title: str, *, minimum: int = MIN_CREATE_TITLE_LENGTH) -> str:
    value = title.strip()
    if not value:
        raise ApiError(400, "invalid_parameter", "论文题目不能为空。")
    if len(value) < minimum:
        raise ApiError(
            400,
            "invalid_parameter",
            f"题目过短（少于 {minimum} 个字符），请确认是否为完整论文题目。",
        )
    if not normalize_title(value):
        raise ApiError(400, "invalid_parameter", "题目缺少可用字符，请检查输入。")
    return value


def validate_conference_year(conference: str, year: int) -> None:
    if conference not in CONFERENCES:
        raise ApiError(
            400,
            "invalid_parameter",
            "会议必须是 CVPR、ICCV、ECCV 之一。",
        )
    if not isinstance(year, int) or year <= 0:
        raise ApiError(400, "invalid_parameter", "年份必须是正整数。")


def find_by_dedup_key(session: Session, dedup_key: str) -> Paper | None:
    return session.exec(select(Paper).where(Paper.dedup_key == dedup_key)).first()


def find_by_source(session: Session, source: str, source_id: str) -> Paper | None:
    row = session.exec(
        select(PaperSource).where(
            PaperSource.source == source, PaperSource.source_id == source_id
        )
    ).first()
    if row is None:
        return None
    return session.get(Paper, row.paper_id)


def attach_source(
    session: Session,
    paper: Paper,
    *,
    source: str,
    source_id: str,
    url: str | None = None,
    retrieved_at: str | None = None,
) -> None:
    """补挂来源标识；已存在同一来源标识时不重复写入。"""
    if paper.id is None:  # pragma: no cover
        raise ValueError("paper 必须先持久化")
    existing = session.exec(
        select(PaperSource).where(
            PaperSource.source == source, PaperSource.source_id == source_id
        )
    ).first()
    if existing is not None:
        return
    session.add(
        PaperSource(
            paper_id=paper.id,
            source=source,
            source_id=source_id,
            url=url,
            retrieved_at=retrieved_at or _now(),
        )
    )


def save_paper(
    session: Session,
    *,
    title: str,
    conference: str,
    year: int,
    abstract: str | None = None,
    author_keywords: list[str] | None = None,
    landing_url: str | None = None,
    pdf_url: str | None = None,
    primary_source: str = "manual",
    data_status: str = "review",
    source_ref: tuple[str, str] | None = None,
    retrieved_at: str | None = None,
) -> tuple[Paper, bool]:
    """统一的保存逻辑：先去重再写入，返回 (论文, 是否新建)。

    去重顺序与设计一致：
    1. 有来源标识时先按 (source, source_id) 命中；
    2. 否则按 dedup_key 命中；
    3. 都未命中则新建，并分配编号。
    命中已有记录时视为同一篇，走更新并补挂来源标识，不产生第二条记录。
    """
    clean_title = validate_title(title)
    validate_conference_year(conference, year)

    existing: Paper | None = None
    if source_ref is not None:
        existing = find_by_source(session, source_ref[0], source_ref[1])
    if existing is None:
        dedup_key = build_dedup_key(conference, year, clean_title)
        existing = find_by_dedup_key(session, dedup_key)

    normalized_abstract = (abstract or "").strip() or None
    keywords = author_keywords or []

    if existing is not None:
        # 更新：补齐缺失字段，不覆盖已有非空内容为空
        if normalized_abstract and existing.abstract != normalized_abstract:
            existing.abstract = normalized_abstract
            existing.abstract_status = "present"
            existing.keyword_status = "pending"
            clear_system_keywords(session, existing.id or 0)
        if landing_url and not existing.landing_url:
            existing.landing_url = landing_url
        if pdf_url and not existing.pdf_url:
            existing.pdf_url = pdf_url
        if keywords:
            existing.keywords_source_json = dump_keywords_json(keywords)
        existing.updated_at = _now()
        session.add(existing)
        session.flush()
        sync_paper_keywords(
            session,
            existing,
            author_keywords=keywords or [],
            system_keywords=None,
        )
        if source_ref is not None:
            attach_source(
                session,
                existing,
                source=source_ref[0],
                source_id=source_ref[1],
                url=landing_url,
            )
        return existing, False

    paper = Paper(
        code="",  # 占位，编号在下方统一分配
        code_origin_conference=conference,
        code_origin_year=year,
        dedup_key=build_dedup_key(conference, year, clean_title),
        title=clean_title,
        title_normalized=normalize_title(clean_title),
        conference=conference,
        year=year,
        abstract=normalized_abstract,
        abstract_status="present" if normalized_abstract else "missing",
        authors_json=None,
        keywords_source_json=dump_keywords_json(keywords),
        landing_url=landing_url or None,
        pdf_url=pdf_url or None,
        primary_source=primary_source,
        data_status=data_status,
        keyword_status="pending",
        keyword_ruleset_version=None,
        keyword_processed_at=None,
        retrieved_at=retrieved_at or _now(),
        created_at=_now(),
        updated_at=_now(),
    )
    paper.code = allocate_code(session, conference, year)
    session.add(paper)
    try:
        session.flush()
    except IntegrityError as error:
        # 并发下两个请求可能同时通过去重查询，其中一个会在唯一索引上失败。
        # 这属于“已存在”，不是服务错误，因此回滚后按冲突语义返回。
        session.rollback()
        dedup_key = build_dedup_key(conference, year, clean_title)
        winner = find_by_dedup_key(session, dedup_key)
        if winner is None and source_ref is not None:
            winner = find_by_source(session, source_ref[0], source_ref[1])
        if winner is not None:
            raise DuplicatePaperError(winner) from error
        raise ApiError(
            409,
            "duplicate_paper",
            "该论文正在被另一个请求写入，请稍后重试。",
        ) from error

    sync_paper_keywords(session, paper, author_keywords=keywords, system_keywords=None)
    if source_ref is not None:
        attach_source(
            session,
            paper,
            source=source_ref[0],
            source_id=source_ref[1],
            url=landing_url,
        )
    return paper, True


def update_paper(
    session: Session,
    paper: Paper,
    *,
    title: str | None = None,
    conference: str | None = None,
    year: int | None = None,
    abstract: str | None = None,
    author_keywords: list[str] | None = None,
    landing_url: str | None = None,
    pdf_url: str | None = None,
    data_status: str | None = None,
) -> Paper:
    """部分更新。题目或摘要变化会使系统关键词失效，退回待处理。

    编号不可修改；会议/年份变更后编号保持不变，但会记录并暴露不一致状态。
    """
    next_title = paper.title if title is None else validate_title(title)
    next_conference = paper.conference if conference is None else conference
    next_year = paper.year if year is None else year
    validate_conference_year(next_conference, next_year)

    if (
        next_title != paper.title
        or next_conference != paper.conference
        or next_year != paper.year
    ):
        dedup_key = build_dedup_key(next_conference, next_year, next_title)
        conflict = find_by_dedup_key(session, dedup_key)
        if conflict is not None and conflict.id != paper.id:
            raise DuplicatePaperError(conflict)
        paper.dedup_key = dedup_key

    title_changed = next_title != paper.title
    paper.title = next_title
    paper.title_normalized = normalize_title(next_title)
    paper.conference = next_conference
    paper.year = next_year

    if abstract is not None:
        cleaned = abstract.strip()
        abstract_changed = (paper.abstract or "") != cleaned
        paper.abstract = cleaned or None
        paper.abstract_status = "present" if cleaned else "missing"
    else:
        abstract_changed = False

    if landing_url is not None:
        paper.landing_url = landing_url.strip() or None
    if pdf_url is not None:
        paper.pdf_url = pdf_url.strip() or None
    if data_status is not None:
        if data_status not in ("complete", "review", "failed"):
            raise ApiError(400, "invalid_parameter", "数据状态取值非法。")
        paper.data_status = data_status

    if author_keywords is not None:
        paper.keywords_source_json = dump_keywords_json(author_keywords)

    if title_changed or abstract_changed:
        # 抽取结果基于旧文本，必须重算；作者关键词来自来源数据，予以保留
        paper.keyword_status = "pending"
        paper.keyword_ruleset_version = None
        paper.keyword_processed_at = None
        clear_system_keywords(session, paper.id or 0)

    paper.updated_at = _now()
    session.add(paper)
    session.flush()

    if author_keywords is not None:
        sync_paper_keywords(
            session,
            paper,
            author_keywords=author_keywords,
            system_keywords=None,
        )
    return paper


def delete_paper(session: Session, paper: Paper) -> None:
    """删除论文。

    paper_keyword 与 paper_source 由外键 ON DELETE CASCADE 清理；
    待办明细中的引用由 ON DELETE SET NULL 置空，保留任务历史。
    编号不回收：conference_year_seq 不回退，保证编号唯一且不复用。
    """
    session.delete(paper)
    session.flush()


def query_papers(
    session: Session,
    *,
    q: str = "",
    match: str = "fuzzy",
    conferences: list[str] | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    keyword: str | None = None,
    topic: str | None = None,
    data_status: str | None = None,
    keyword_status: str | None = None,
    sort: str = "code",
    order: str = "asc",
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> dict[str, object]:
    """检索论文：精确/模糊匹配 + 组合筛选 + 稳定排序 + 分页。"""
    if sort not in SORT_FIELDS:
        raise ApiError(400, "invalid_parameter", f"排序字段必须是 {'/'.join(SORT_FIELDS)} 之一。")
    if order not in ("asc", "desc"):
        raise ApiError(400, "invalid_parameter", "排序方向必须是 asc 或 desc。")
    if match not in ("fuzzy", "exact"):
        raise ApiError(400, "invalid_parameter", "匹配方式必须是 fuzzy 或 exact。")
    if year_from is not None and year_to is not None and year_from > year_to:
        raise ApiError(400, "invalid_parameter", "起始年份不能大于结束年份。")
    if page < 1:
        raise ApiError(400, "invalid_parameter", "页码必须大于等于 1。")
    if page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise ApiError(400, "invalid_parameter", f"每页条数必须在 1 到 {MAX_PAGE_SIZE} 之间。")
    if conferences:
        invalid = [item for item in conferences if item not in CONFERENCES]
        if invalid:
            raise ApiError(
                400,
                "invalid_parameter",
                f"会议取值非法：{'、'.join(invalid)}。只允许 CVPR、ICCV、ECCV。",
            )

    statement = select(Paper)
    count_statement = select(func.count()).select_from(Paper)

    conditions = []
    if conferences:
        conditions.append(col(Paper.conference).in_(conferences))
    if year_from is not None:
        conditions.append(Paper.year >= year_from)
    if year_to is not None:
        conditions.append(Paper.year <= year_to)
    if data_status:
        if data_status not in DATA_STATUSES:
            raise ApiError(
                400,
                "invalid_parameter",
                f"数据状态必须是 {'/'.join(DATA_STATUSES)} 之一，收到 {data_status}。",
            )
        conditions.append(Paper.data_status == data_status)
    if keyword_status:
        if keyword_status not in KEYWORD_STATUSES:
            raise ApiError(
                400,
                "invalid_parameter",
                f"关键词处理状态必须是 {'/'.join(KEYWORD_STATUSES)} 之一，收到 {keyword_status}。",
            )
        conditions.append(Paper.keyword_status == keyword_status)

    needle = q.strip()
    if needle:
        lowered = needle.lower()
        if match == "exact":
            conditions.append(
                (Paper.title_normalized == normalize_title(needle))
                | (func.lower(Paper.code) == lowered)
            )
        else:
            # 查询词必须与存储标题使用同一套归一化规则，否则含连字符或标点的标题
            # （如 Self-Supervised）在模糊匹配下会查不到：“self-supervised” 不是
            # “self supervised” 的子串。编号保留原始字符单独比较。
            normalized_needle = normalize_title(needle)
            # 关键词串匹配用 EXISTS 子查询，避免 JOIN 造成的行重复
            keyword_like = (
                select(PaperKeyword.id)
                .join(Keyword, Keyword.id == PaperKeyword.keyword_id)
                .where(
                    PaperKeyword.paper_id == Paper.id,
                    func.lower(Keyword.name).like(f"%{lowered}%"),
                )
            )
            like_clauses = [
                func.lower(Paper.code).like(f"%{lowered}%"),
                keyword_like.exists(),
            ]
            if normalized_needle:
                like_clauses.append(
                    Paper.title_normalized.like(f"%{normalized_needle}%")
                )
            conditions.append(or_(*like_clauses))

    if keyword:
        normalized = normalize_keyword(keyword)
        keyword_exists = (
            select(PaperKeyword.id)
            .join(Keyword, Keyword.id == PaperKeyword.keyword_id)
            .where(
                PaperKeyword.paper_id == Paper.id,
                Keyword.name_normalized == normalized,
            )
        )
        conditions.append(keyword_exists.exists())

    if topic:
        topic_exists = (
            select(PaperKeyword.id)
            .join(Keyword, Keyword.id == PaperKeyword.keyword_id)
            .where(
                PaperKeyword.paper_id == Paper.id,
                Keyword.topic_id == _topic_id_for(session, topic),
            )
        )
        conditions.append(topic_exists.exists())

    for condition in conditions:
        statement = statement.where(condition)
        count_statement = count_statement.where(condition)

    sort_column = {
        "code": Paper.code,
        "title": Paper.title_normalized,
        "year": Paper.year,
        "conference": Paper.conference,
        "created_at": Paper.created_at,
    }[sort]
    ordered = sort_column.desc() if order == "desc" else sort_column.asc()
    # 稳定次级键：避免同值行在分页之间跳动
    statement = statement.order_by(ordered, Paper.id.asc())

    total = int(session.exec(count_statement).one())
    pages = max(1, (total + page_size - 1) // page_size)
    effective_page = min(max(1, page), pages)
    offset = (effective_page - 1) * page_size
    items = session.exec(statement.offset(offset).limit(page_size)).all()

    return {
        "items": list(items),
        "total": total,
        "page": effective_page,
        "page_size": page_size,
        "pages": pages,
    }


def _topic_id_for(session: Session, topic: str) -> int:
    """把主题标识（slug 或展示名）解析为 topic.id；不存在时返回 -1（不匹配任何行）。"""
    from ..models.entities import Topic

    row = session.exec(
        select(Topic).where((Topic.slug == topic) | (Topic.name == topic))
    ).first()
    return row.id if row is not None and row.id is not None else -1


def related_papers(session: Session, paper: Paper, *, limit: int = 3) -> list[Paper]:
    """同主题论文：按该系统关键词归属的主题找其他论文。"""
    topic_ids = session.exec(
        select(Keyword.topic_id)
        .join(PaperKeyword, PaperKeyword.keyword_id == Keyword.id)
        .where(
            PaperKeyword.paper_id == paper.id,
            Keyword.origin == "system",
            col(Keyword.topic_id).is_not(None),
        )
        .distinct()
    ).all()
    if not topic_ids:
        return []
    candidate_ids = session.exec(
        select(PaperKeyword.paper_id)
        .join(Keyword, Keyword.id == PaperKeyword.keyword_id)
        .where(
            col(Keyword.topic_id).in_([item for item in topic_ids if item is not None]),
            PaperKeyword.paper_id != paper.id,
        )
        .distinct()
        .limit(limit)
    ).all()
    if not candidate_ids:
        return []
    return list(
        session.exec(
            select(Paper)
            .where(col(Paper.id).in_(list(candidate_ids)))
            .order_by(Paper.code)
        ).all()
    )


def load_paper_keywords(
    session: Session,
    paper_ids: list[int],
    *,
    ruleset_version: str | None = None,
) -> dict[int, list[dict[str, object]]]:
    """批量取回论文的关键词标签（含来源与主题名），避免逐行查询。

    版本过滤是必需的：paper_keyword 允许同一 (论文, 关键词) 保留多个规则版本，
    重算后若不过滤，详情页会同时出现新旧两套词，甚至出现已被淘汰的旧词。
    - 系统关键词：只取当前规则版本的结果（与统计口径 v_analysis_keyword 一致）；
    - 作者关键词：来自来源数据，与抽取规则版本无关，始终返回。
    """
    if not paper_ids:
        return {}
    from ..models.entities import Topic

    current = ruleset_version or current_ruleset_version(session)
    rows = session.exec(
        select(PaperKeyword, Keyword, Topic)
        .join(Keyword, Keyword.id == PaperKeyword.keyword_id)
        .join(Topic, Topic.id == Keyword.topic_id, isouter=True)
        .where(
            col(PaperKeyword.paper_id).in_(paper_ids),
            or_(
                Keyword.origin == "author",
                PaperKeyword.ruleset_version == current,
            ),
        )
        .order_by(PaperKeyword.paper_id, Keyword.origin.desc(), PaperKeyword.rank)
    ).all()

    grouped: dict[int, list[dict[str, object]]] = {
        paper_id: [] for paper_id in paper_ids
    }
    seen: dict[int, set[tuple[str, str]]] = {paper_id: set() for paper_id in paper_ids}
    for paper_keyword, keyword, topic in rows:
        # 同一来源 + 同一归一形式只保留一条，防止历史数据里出现重复标签
        marker = (keyword.origin, keyword.name_normalized)
        if marker in seen.setdefault(paper_keyword.paper_id, set()):
            continue
        seen[paper_keyword.paper_id].add(marker)
        grouped.setdefault(paper_keyword.paper_id, []).append(
            {
                "name": keyword.name,
                "origin": keyword.origin,
                "topic": topic.name if topic is not None else None,
            }
        )
    return grouped


def load_paper_sources(
    session: Session, paper_ids: list[int]
) -> dict[int, list[dict[str, object]]]:
    if not paper_ids:
        return {}
    rows = session.exec(
        select(PaperSource).where(col(PaperSource.paper_id).in_(paper_ids))
    ).all()
    grouped: dict[int, list[dict[str, object]]] = {
        paper_id: [] for paper_id in paper_ids
    }
    for row in rows:
        grouped.setdefault(row.paper_id, []).append(
            {
                "source": row.source,
                "source_id": row.source_id,
                "url": row.url,
                "retrieved_at": row.retrieved_at,
            }
        )
    return grouped


def serialize_authors(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def analysis_title_threshold() -> int:
    """分析集合的最小标题长度，供文档与校验共同引用。"""
    return MIN_ANALYSIS_TITLE_LENGTH

def find_existing_paper(
    session: Session,
    *,
    title: str,
    conference: str | None = None,
    year: int | None = None,
) -> Paper | None:
    """判断一篇论文是否已在库中（用于「重复」判定）。

    刻意**只做精确匹配**：会议年份已知时按去重键查，否则按归一化标题全等查。
    不能用模糊/子串匹配——曾经用模糊检索做重复判定，把
    「DA-VPT: Semantic-Guided Visual Prompt Tuning for Vision Transformers」
    当成了「Visual Prompt Tuning」的重复，导致一篇独立论文被静默跳过。
    """
    normalized = normalize_title(title)
    if conference and year:
        # 会议年份已知：只认去重键。**不再退回全库同名查询**，
        # 否则同名但属于不同会议年份的论文（例如同一题目出现在两个会议索引里）
        # 会被误判成重复而静默跳过。
        return find_by_dedup_key(session, build_dedup_key(conference, year, title))
    if not normalized:
        return None
    # 只有会议年份未知时才按标题全等查，作为兜底
    return session.exec(
        select(Paper).where(Paper.title_normalized == normalized)
    ).first()
