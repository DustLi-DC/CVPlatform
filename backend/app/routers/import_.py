"""批量导入与任务接口。

契约见 开发设计与验收.md 第 7.4 节。预览只解析不写库，确认后才创建任务；
任务计数来自明细状态的实际统计，进度不使用估算值。
"""

from __future__ import annotations

from fastapi import APIRouter, File, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlmodel import col, select

from ..db.engine import session_scope
from ..models.entities import CollectionTask, CollectionTaskItem
from ..services import importer, tasks
from ..services.papers import ApiError

router = APIRouter(prefix="/api/import", tags=["import"])


class PreviewRowOut(BaseModel):
    line_no: int
    title: str
    conference: str | None = None
    year: int | None = None
    status: str
    message: str | None = None


class PreviewResponse(BaseModel):
    file_name: str
    file_format: str
    total_lines: int
    valid_count: int
    invalid_count: int
    duplicate_in_file_count: int
    blank_count: int
    importable_count: int
    warnings: list[str] = []
    rows: list[PreviewRowOut] = []


class TaskItemOut(BaseModel):
    line_no: int
    input_title: str
    input_conference: str | None = None
    input_year: int | None = None
    status: str
    paper_id: int | None = None
    duplicate_of_paper_id: int | None = None
    message: str | None = None
    attempts: int


class TaskOut(BaseModel):
    id: int
    kind: str
    file_name: str | None = None
    file_format: str | None = None
    sample_stride: int | None = None
    sample_limit: int | None = None
    status: str
    message: str | None = None
    total_count: int
    pending_count: int
    running_count: int
    success_count: int
    duplicate_count: int
    failed_count: int
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    resumable: bool = Field(description="是否还有未完成条目可继续处理")


class TaskListOut(BaseModel):
    items: list[TaskOut]
    total: int


class TaskDetailOut(TaskOut):
    items: list[TaskItemOut] = []


class TemplateOut(BaseModel):
    txt_template: str
    csv_template: str
    field_notes: list[dict[str, str]]
    max_rows: int
    max_bytes: int


def _to_task_out(task: CollectionTask) -> TaskOut:
    return TaskOut(
        id=task.id or 0,
        kind=task.kind,
        file_name=task.file_name,
        file_format=task.file_format,
        sample_stride=task.sample_stride,
        sample_limit=task.sample_limit,
        status=task.status,
        message=task.message,
        total_count=task.total_count,
        pending_count=task.pending_count,
        running_count=task.running_count,
        success_count=task.success_count,
        duplicate_count=task.duplicate_count,
        failed_count=task.failed_count,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
        resumable=bool(task.pending_count or task.running_count),
    )


def _to_item_out(item: CollectionTaskItem) -> TaskItemOut:
    return TaskItemOut(
        line_no=item.line_no,
        input_title=item.input_title,
        input_conference=item.input_conference,
        input_year=item.input_year,
        status=item.status,
        paper_id=item.paper_id,
        duplicate_of_paper_id=item.duplicate_of_paper_id,
        message=item.message,
        attempts=item.attempts,
    )


@router.get("/template", response_model=TemplateOut, summary="导入模板与字段说明")
def get_template() -> TemplateOut:
    from ..config import IMPORT_MAX_BYTES, IMPORT_MAX_ROWS

    return TemplateOut(
        txt_template=importer.TEMPLATE_TXT,
        csv_template=importer.TEMPLATE_CSV,
        field_notes=[dict(item) for item in importer.FIELD_NOTES],
        max_rows=IMPORT_MAX_ROWS,
        max_bytes=IMPORT_MAX_BYTES,
    )


@router.post("/preview", response_model=PreviewResponse, summary="解析文件并预览（不写库）")
async def preview_file(file: UploadFile = File(...)) -> PreviewResponse:
    raw = await file.read()
    try:
        result = importer.parse_file(file.filename or "", raw)
    except importer.ImportFileError as error:
        status_code = {
            "unsupported_file_type": 415,
            "file_too_large": 413,
            "too_many_rows": 413,
            "unsupported_encoding": 400,
        }.get(error.code, 400)
        raise ApiError(status_code, error.code, error.message) from error

    return PreviewResponse(
        file_name=file.filename or "",
        file_format=result.file_format,
        total_lines=result.total_lines,
        valid_count=result.valid_count,
        invalid_count=result.invalid_count,
        duplicate_in_file_count=result.duplicate_in_file_count,
        blank_count=result.blank_count,
        importable_count=result.importable_count,
        warnings=result.warnings,
        rows=[
            PreviewRowOut(
                line_no=row.line_no,
                title=row.title,
                conference=row.conference,
                year=row.year,
                status=row.status,
                message=row.message,
            )
            for row in result.rows
        ],
    )


@router.post("/tasks", response_model=TaskOut, status_code=status.HTTP_202_ACCEPTED,
             summary="创建批量导入任务并开始处理")
async def create_task(file: UploadFile = File(...)) -> TaskOut:
    raw = await file.read()
    try:
        result = importer.parse_file(file.filename or "", raw)
    except importer.ImportFileError as error:
        status_code = {
            "unsupported_file_type": 415,
            "file_too_large": 413,
            "too_many_rows": 413,
            "unsupported_encoding": 400,
        }.get(error.code, 400)
        raise ApiError(status_code, error.code, error.message) from error

    rows = [
        (row.line_no, row.title, row.conference, row.year)
        for row in result.rows
        if row.status == "ok"
    ]
    if not rows:
        raise ApiError(400, "no_valid_rows", "文件里没有可导入的有效行。")

    with session_scope() as session:
        task = tasks.create_batch_task(
            session,
            file_name=file.filename or "",
            file_size=len(raw),
            file_format=result.file_format,
            rows=rows,
        )
        task_id = task.id or 0
        payload = _to_task_out(task)

    started = tasks.runner.start(task_id)
    if not started:
        # 已有任务在跑：保持 pending，稍后可继续处理
        payload.message = "已排队：当前有其他任务在处理，稍后自动开始或手动继续。"
    return payload


@router.get("/tasks", response_model=TaskListOut, summary="任务列表（刷新后仍可查看）")
def list_tasks(limit: int = Query(20, ge=1, le=100)) -> TaskListOut:
    with session_scope() as session:
        rows = session.exec(
            select(CollectionTask).order_by(col(CollectionTask.id).desc()).limit(limit)
        ).all()
        total = len(
            session.exec(select(CollectionTask)).all()
        )
        return TaskListOut(items=[_to_task_out(task) for task in rows], total=total)


@router.get("/tasks/{task_id}", response_model=TaskDetailOut, summary="任务详情与逐项结果")
def get_task(
    task_id: int,
    item_status: str | None = Query(None, description="按明细状态筛选"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> TaskDetailOut:
    with session_scope() as session:
        task = session.get(CollectionTask, task_id)
        if task is None:
            raise ApiError(404, "task_not_found", "任务不存在。")
        statement = select(CollectionTaskItem).where(
            CollectionTaskItem.task_id == task_id
        )
        if item_status:
            if item_status not in tasks.ITEM_STATUSES:
                raise ApiError(
                    400,
                    "invalid_parameter",
                    f"明细状态必须是 {'/'.join(tasks.ITEM_STATUSES)} 之一。",
                )
            statement = statement.where(CollectionTaskItem.status == item_status)
        statement = (
            statement.order_by(CollectionTaskItem.line_no)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = session.exec(statement).all()
        base = _to_task_out(task)
        return TaskDetailOut(
            **base.model_dump(), items=[_to_item_out(item) for item in items]
        )


@router.post("/tasks/{task_id}/resume", response_model=TaskOut, summary="继续处理未完成条目")
def resume_task(task_id: int) -> TaskOut:
    with session_scope() as session:
        task = tasks.resume_task(session, task_id)
        payload = _to_task_out(task)
    tasks.runner.start(task_id)
    return payload


@router.post("/tasks/{task_id}/retry", response_model=TaskOut, summary="重试失败条目")
def retry_task(task_id: int) -> TaskOut:
    with session_scope() as session:
        task = tasks.retry_failed(session, task_id)
        payload = _to_task_out(task)
    tasks.runner.start(task_id)
    return payload
