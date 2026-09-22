"""外部来源的 HTTP 访问层：超时、限速与有限重试集中在这里。

设计依据：开发设计与验收.md 第 8.2、8.4 节——出站请求并发默认 1、间隔 0.5 秒，
遇限流主动退避；使用标准库 urllib，不引入额外依赖。

错误分为两类，供接口层区分「超时」与「来源不可用」：
- SourceTimeout：连不上或超过超时时间；
- SourceUnavailable：收到非 2xx 响应，或达到重试上限仍失败。
"""

from __future__ import annotations

import logging
import os
import threading
import time
import urllib.error
import urllib.request

logger = logging.getLogger("cvplatform.sources")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
API_USER_AGENT = "CVPlatform/0.1 (course project; mailto:course@example.com)"


class SourceError(Exception):
    """外部来源访问失败的基类。"""

    def __init__(self, source: str, message: str) -> None:
        super().__init__(message)
        self.source = source
        self.message = message


class SourceTimeout(SourceError):
    """请求超时或网络不可达。"""


class SourceUnavailable(SourceError):
    """来源返回错误状态，或重试后仍然失败。"""

    def __init__(self, source: str, message: str, status: int | None = None) -> None:
        super().__init__(source, message)
        self.status = status


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


class RateLimiter:
    """全局限速：保证相邻两次出站请求之间至少间隔 interval 秒。

    单 worker + 单实例场景下用一个进程内锁即可；批次任务与单篇采集共用同一个限速器，
    避免并发叠加把来源打挂。
    """

    def __init__(self, interval_seconds: float) -> None:
        self._interval = interval_seconds
        self._lock = threading.Lock()
        self._last_at = 0.0

    @property
    def interval(self) -> float:
        return self._interval

    def increase(self, factor: float = 2.0, cap: float = 10.0) -> float:
        """遇到限流时提高间隔（主动退避），并返回新值。"""
        with self._lock:
            self._interval = min(cap, max(0.0, self._interval * factor))
            return self._interval

    def wait(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_at
            delay = self._interval - elapsed
            if delay > 0:
                time.sleep(delay)
            self._last_at = time.monotonic()


# 单例：间隔由环境变量控制，默认 0.5 秒
limiter = RateLimiter(_env_float("HTTP_INTERVAL_SECONDS", 0.5))


def fetch_text(
    url: str,
    *,
    source: str,
    timeout: float | None = None,
    retries: int | None = None,
    accept: str = "text/html,application/xhtml+xml",
    user_agent: str = DEFAULT_USER_AGENT,
) -> str:
    """抓取文本内容。超时、限速与重试策略统一在此实现。

    retries 表示**重试次数**（不含首次请求），默认 2 次，即最多请求 3 次。
    """
    timeout_value = (
        timeout if timeout is not None else _env_float("HTTP_TIMEOUT_SECONDS", 10.0)
    )
    retry_count = retries if retries is not None else _env_int("HTTP_RETRIES", 2)
    backoff = 1.0
    last_error: Exception | None = None

    for attempt in range(retry_count + 1):
        limiter.wait()
        request = urllib.request.Request(
            url,
            headers={"User-Agent": user_agent, "Accept": accept},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_value) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, "replace")
        except urllib.error.HTTPError as error:
            last_error = error
            status = error.code
            if status in (429, 403):
                # 被限流：主动提高全局限速间隔后再重试
                new_interval = limiter.increase()
                logger.warning(
                    "%s 返回 %s，疑似限流，请求间隔提高到 %.1fs", source, status, new_interval
                )
            elif status < 500:
                # 4xx（如 404）不重试，立即上报
                raise SourceUnavailable(
                    source, f"{source} 返回 HTTP {status}", status
                ) from error
        except TimeoutError as error:
            # socket 超时在 3.10+ 是 TimeoutError；10 以前是 socket.timeout
            last_error = error
        except urllib.error.URLError as error:
            last_error = error
            if isinstance(error.reason, TimeoutError):
                last_error = error.reason

        if attempt < retry_count:
            time.sleep(backoff)
            backoff *= 2

    if isinstance(last_error, (TimeoutError,)) or (
        isinstance(last_error, urllib.error.URLError)
        and isinstance(last_error.reason, TimeoutError)
    ):
        # 超时值可能小于 1 秒（例如按环境变量收紧），用 %g 保留有效数字，
        # 避免 0.001 秒被显示成「0 秒」这种没有信息量的文案
        display = f"{timeout_value:g}"
        raise SourceTimeout(source, f"{source} 请求超时（{display} 秒）")
    if isinstance(last_error, urllib.error.HTTPError):
        raise SourceUnavailable(
            source, f"{source} 返回 HTTP {last_error.code}", last_error.code
        )
    raise SourceUnavailable(source, f"{source} 请求失败：{last_error}")


def fetch_json(
    url: str,
    *,
    source: str,
    timeout: float | None = None,
    retries: int | None = None,
) -> object:
    """抓取 JSON 内容（用于 OpenAlex 等接口）。"""
    import json

    text = fetch_text(
        url,
        source=source,
        timeout=timeout,
        retries=retries,
        accept="application/json",
        user_agent=API_USER_AGENT,
    )
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise SourceUnavailable(source, f"{source} 返回的内容不是合法 JSON") from error
