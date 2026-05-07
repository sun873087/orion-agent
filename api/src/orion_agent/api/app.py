"""FastAPI app — 主體 + lifespan + CORS + 路由註冊。

對應 spec § 5 app.py。

Lifespan 期間建立的共用資源:
- SessionManager(in-memory)
- LLMProvider(從 ORION_PROVIDER / ORION_MODEL env)

Phase 7 會加 Postgres pool / Redis 等。
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# 載入 .env 讓 API key 等可用 — main.py 已 load,但獨立啟 app(uvicorn 直跑)需要
load_dotenv()

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from orion_agent.api.deps import _provider_from_env  # noqa: E402
from orion_agent.api.routes import auth as auth_router  # noqa: E402
from orion_agent.api.routes import chat as chat_router  # noqa: E402
from orion_agent.api.routes import health as health_router  # noqa: E402
from orion_agent.api.routes import sessions as sessions_router  # noqa: E402
from orion_agent.api.routes import uploads as uploads_router  # noqa: E402
from orion_agent.api.session_manager import SessionManager  # noqa: E402
from orion_agent.api.session_manager_db import DbSessionManager  # noqa: E402
from orion_agent.commands.registry import register_builtins  # noqa: E402
from orion_agent.hooks.events import SetupEvent  # noqa: E402
from orion_agent.hooks.registry import HookRegistry  # noqa: E402
from orion_agent.services.logging import (  # noqa: E402
    configure_logging,
    request_id_middleware,
)
from orion_agent.storage.db.engine import create_db_engine, init_db  # noqa: E402


def _cors_origins() -> list[str]:
    """從 ORION_CORS_ORIGINS env 讀(逗號分隔),預設給 dev 前端。"""
    raw = os.environ.get("ORION_CORS_ORIGINS")
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return [
        "http://localhost:5173",  # vite
        "http://localhost:3000",  # CRA / next
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
        "null",  # 給直接 file:// 開 test-ui.html 用
    ]


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """startup / shutdown hooks。

    Phase 7:
    - configure_logging:structlog initialize
    - 若 ORION_DB_URL 設 → 起 DB engine + init_db,SessionManager 切 DbSessionManager
      否則 → in-memory SessionManager(Phase 6 行為)
    """
    configure_logging()

    # Phase 11:註冊內建 slash 命令(/help / /model)— idempotent
    register_builtins()

    db_url = os.environ.get("ORION_DB_URL")
    db_engine = None
    if db_url:
        db_engine = create_db_engine(db_url)
        # 自動建表(production 應改走 Alembic);Phase 7 預設 SQLite/dev 友善
        if os.environ.get("ORION_DB_AUTO_CREATE", "1") != "0":
            await init_db(db_engine)
        app.state.db_engine = db_engine
        app.state.session_manager = DbSessionManager(engine=db_engine)
    else:
        app.state.db_engine = None
        app.state.session_manager = SessionManager()

    app.state.llm_provider = _provider_from_env()

    # Phase 8:全域 HookRegistry(routes / chat 用,讓 plugin / settings 註冊到此)
    hooks = HookRegistry()
    app.state.hooks = hooks
    await hooks.fire(SetupEvent(session_id=None, user_id=None))

    try:
        yield
    finally:
        if db_engine is not None:
            await db_engine.dispose()


def create_app() -> FastAPI:
    """工廠 — uvicorn 入口 / 測試用。"""
    app = FastAPI(
        title="orion-agent",
        version="0.1.0",
        description=(
            "Multi-LLM agent harness — Phase 6 FastAPI layer. "
            "WebSocket /chat/stream + REST /sessions + JWT /auth/login."
        ),
        lifespan=_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Phase 7:request_id middleware(每 request 產 UUID,bind structlog contextvars)
    app.middleware("http")(request_id_middleware)

    app.include_router(health_router.router)
    app.include_router(auth_router.router)
    app.include_router(sessions_router.router)
    app.include_router(uploads_router.router)
    app.include_router(chat_router.router)

    return app


# Module-level app 給 `uvicorn orion_agent.api.app:app` 用
app = create_app()
