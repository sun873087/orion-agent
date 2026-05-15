"""structlog config + request_id middleware。"""

from __future__ import annotations

import structlog

from orion_sdk.services.logging import (
    configure_logging,
    get_logger,
    request_id_middleware,
)


def test_configure_logging_idempotent() -> None:
    configure_logging()
    configure_logging()  # 重複呼不能炸


def test_get_logger_returns_bound_logger() -> None:
    log = get_logger("test")
    assert hasattr(log, "info")


def test_request_id_middleware_is_callable() -> None:
    # middleware 是 async function;不在 fastapi runtime 內難跑完整流程,
    # 起碼確保 import / signature OK 不會 break app 啟動。
    assert callable(request_id_middleware)


def test_contextvars_bind() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id="abc")
    # 不直接檢測 ctx — 確保 API 可呼叫即可
    structlog.contextvars.clear_contextvars()
