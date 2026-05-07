"""Structured logging via structlog — Phase 7。

對應 Phase 7 spec § 4.3 telemetry/observability(基礎)。

兩種 renderer:
- production:JSON(易進 CloudWatch / Loki / Datadog)
- dev:console(顏色易讀)

`ORION_LOG_FORMAT=json` 強制 JSON;否則:tty=console、pipe=json。
`ORION_LOG_LEVEL=debug|info|warning|error` 設等級,預設 info。

Caller 用 `get_logger(__name__).info("event", key=value)` 即可,不用調 stdlib logging。

request_id middleware:每 request 產 UUID,bind 到 contextvars,後續 log 自動帶。
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

import structlog
from fastapi import Request, Response

_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "warn": logging.WARNING,
    "error": logging.ERROR,
}


def _level_from_env() -> int:
    raw = os.environ.get("ORION_LOG_LEVEL", "info").lower().strip()
    return _LEVELS.get(raw, logging.INFO)


def _use_json_format() -> bool:
    """`ORION_LOG_FORMAT=json` 強制;否則看是否 tty。"""
    forced = os.environ.get("ORION_LOG_FORMAT", "").lower()
    if forced == "json":
        return True
    if forced == "console":
        return False
    return not sys.stderr.isatty()


def configure_logging() -> None:
    """初始化 structlog + stdlib logging。應用啟動時(lifespan)呼一次。"""
    level = _level_from_env()
    use_json = _use_json_format()

    timestamper = structlog.processors.TimeStamper(fmt="iso")

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        timestamper,
    ]

    if use_json:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    # 也統一 stdlib logging 的 level(其他 lib 用 logging.getLogger(...))
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        stream=sys.stderr,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """便利 wrapper。caller 直接 `log = get_logger(__name__)`。"""
    log: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return log


# ─── FastAPI middleware:request_id ─────────────────────────────────────────


async def request_id_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """每 request 產 UUID,bind 到 structlog contextvars。

    Response header `X-Request-ID` 也帶,client 可 grep 同一 request 的所有 log。
    """
    rid = request.headers.get("X-Request-ID") or uuid4().hex[:16]
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        request_id=rid,
        method=request.method,
        path=request.url.path,
    )
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response
