"""FastAPI 入口：服务信息、健康检查、数据库初始化与统一错误响应。

错误响应统一为 {"detail": {"code", "message"}}，与 开发设计与验收.md 第 7.6 节一致；
未知错误只记录日志，不把内部路径与堆栈返回给调用方。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import load_settings
from .db.engine import init_database
from .routers import papers
from .services.papers import ApiError


def _configure_logging() -> logging.Logger:
    """确保应用日志一定会输出。

    uvicorn 只为自己命名空间的 logger 安装处理器，根 logger 默认没有处理器，
    应用 logger 的 INFO 记录会被静默丢弃。这里在没有处理器时补一个，
    使部署文档里 `journalctl -u cvplatform | grep 数据库就绪` 的检查方式成立。
    """
    app_logger = logging.getLogger("cvplatform")
    if not app_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )
        app_logger.addHandler(handler)
        app_logger.setLevel(logging.INFO)
        app_logger.propagate = False
    return app_logger


logger = _configure_logging()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """启动时初始化或升级数据库；可重复启动，数据保留。"""
    settings = load_settings()
    summary = init_database()
    logger.info(
        "数据库就绪：%s（环境 %s，结构版本 v%s → v%s，本次应用迁移 %s）",
        summary["database_path"],
        settings.environment,
        summary["from_version"],
        summary["to_version"],
        summary["applied"] or "无",
    )
    yield


app = FastAPI(title="CVPlatform API", version="0.2.0", lifespan=lifespan)


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str = "CVPlatform API"


@app.get("/api/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    """Report that the API is running."""
    return HealthResponse()


@app.exception_handler(ApiError)
async def handle_api_error(_request: Request, error: ApiError) -> JSONResponse:
    body: dict[str, object] = {"code": error.code, "message": error.message}
    body.update(error.extra)
    return JSONResponse(status_code=error.status_code, content={"detail": body})


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    _request: Request, error: RequestValidationError
) -> JSONResponse:
    """参数校验失败统一映射为 400 invalid_parameter，并保留出错字段。"""
    details = [
        {
            "field": ".".join(
                str(part) for part in item.get("loc", ()) if part != "body"
            ),
            "message": item.get("msg", "参数不合法"),
        }
        for item in error.errors()
    ]
    message = "；".join(
        f"{item['field']}：{item['message']}" if item["field"] else str(item["message"])
        for item in details
    )
    return JSONResponse(
        status_code=400,
        content={
            "detail": {
                "code": "invalid_parameter",
                "message": message or "参数不合法",
                "fields": details,
            }
        },
    )


@app.exception_handler(StarletteHTTPException)
async def handle_http_error(
    _request: Request, error: StarletteHTTPException
) -> JSONResponse:
    """保留 404 等框架级错误的语义，同时使用统一响应结构。

    400 一律归入 invalid_parameter：请求体格式错误与参数越界对调用方是同一类问题，
    不应让同一类错误出现两种错误码。
    """
    code = {
        400: "invalid_parameter",
        404: "not_found",
        405: "method_not_allowed",
        415: "unsupported_media_type",
    }.get(error.status_code, "http_error")
    return JSONResponse(
        status_code=error.status_code,
        content={"detail": {"code": code, "message": str(error.detail)}},
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(_request: Request, error: Exception) -> JSONResponse:
    logger.exception("未处理的服务异常：%s", error)
    return JSONResponse(
        status_code=500,
        content={"detail": {"code": "internal_error", "message": "服务内部错误，请稍后重试。"}},
    )


app.include_router(papers.router)
