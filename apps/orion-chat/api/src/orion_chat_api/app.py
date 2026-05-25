"""FastAPI app — 主體 + lifespan + CORS + 路由註冊。

對應 spec § 5 app.py。

Lifespan 期間建立的共用資源:
- SessionManager(in-memory)
- LLMProvider(從 ORION_PROVIDER / ORION_MODEL env)

會加 Postgres pool / Redis 等。
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from dotenv import load_dotenv

# 載入 per-app .env(apps/orion-chat/.env)讓 API key 等可用 — cli.py 已 load,
# 但獨立啟 app(uvicorn 直跑)需要。不抓 project root .env。
load_dotenv(Path(__file__).resolve().parents[3] / ".env")

from fastapi import FastAPI # noqa: E402
from fastapi.middleware.cors import CORSMiddleware # noqa: E402

from orion_chat_api.deps import _provider_from_env # noqa: E402
from orion_chat_api.routes import auth as auth_router # noqa: E402
from orion_chat_api.routes import chat as chat_router # noqa: E402
from orion_chat_api.routes import collaborations as collaborations_router # noqa: E402
from orion_chat_api.routes import health as health_router # noqa: E402
from orion_chat_api.routes import mcp as mcp_router # noqa: E402
from orion_chat_api.routes import memories as memories_router # noqa: E402
from orion_chat_api.routes import oauth as oauth_router # noqa: E402
from orion_chat_api.routes import plan as plan_router # noqa: E402
from orion_chat_api.routes import preferences as preferences_router # noqa: E402
from orion_chat_api.routes import projects as projects_router # noqa: E402
from orion_chat_api.routes import roles as roles_router # noqa: E402
from orion_chat_api.routes import schedules as schedules_router # noqa: E402
from orion_chat_api.routes import sessions as sessions_router # noqa: E402
from orion_chat_api.routes import skills as skills_router # noqa: E402
from orion_chat_api.routes import soul as soul_router # noqa: E402
from orion_chat_api.routes import uploads as uploads_router # noqa: E402
from orion_chat_api.routes import user_settings as user_settings_router # noqa: E402
from orion_chat_api.routes import voice as voice_router # noqa: E402
from orion_chat_api.session_manager import SessionManager # noqa: E402
from orion_chat_api.session_manager_db import DbSessionManager # noqa: E402
from orion_cli.commands.registry import register_builtins # noqa: E402
from orion_sdk.hooks.events import SetupEvent # noqa: E402
from orion_sdk.hooks.registry import HookRegistry # noqa: E402
from orion_sdk.services.logging import ( # noqa: E402
    configure_logging,
    request_id_middleware,
)
from orion_sdk.storage.db.engine import create_db_engine, init_db # noqa: E402


def _cors_origins() -> list[str]:
    """從 ORION_CORS_ORIGINS env 讀(逗號分隔),預設給 dev 前端。"""
    raw = os.environ.get("ORION_CORS_ORIGINS")
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return [
        "http://localhost:5173", # vite
        "http://localhost:3000", # CRA / next
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
        "null", # 給直接 file:// 開 test-ui.html 用
    ]


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """startup / shutdown hooks。

   :
    - configure_logging:structlog initialize
    - 若 ORION_DB_URL 設 → 起 DB engine + init_db,SessionManager 切 DbSessionManager
      否則 → in-memory SessionManager(行為)
    """
    configure_logging()

    # 跑 settings migrations(沒 settings.json 就略過,有 pending 才跑)
    from orion_sdk.migrations import run_pending_migrations
    try:
        result = run_pending_migrations()
        if result.applied:
            import structlog
            structlog.get_logger().info(
                "settings_migrations_applied",
                from_version=result.from_version,
                to_version=result.to_version,
                applied=result.applied,
                backup=str(result.backup_path) if result.backup_path else None,
            )
    except Exception as e: # noqa: BLE001 — 啟動失敗 fallback 不阻擋 server
        import structlog
        structlog.get_logger().error("settings_migrations_failed", error=str(e))

    # 註冊內建 slash 命令(/help / /model)— idempotent
    register_builtins()

    db_url = os.environ.get("ORION_DB_URL")
    db_engine = None
    if db_url:
        db_engine = create_db_engine(db_url)
        # 自動建表(production 應改走 Alembic) 預設 SQLite/dev 友善
        if os.environ.get("ORION_DB_AUTO_CREATE", "1") != "0":
            await init_db(db_engine)
        app.state.db_engine = db_engine
        sm_db = DbSessionManager(engine=db_engine)
        app.state.session_manager = sm_db
        # 啟動時清掉 fs 上的孤兒 session 目錄(DB 已不存在但磁碟還在)
        try:
            removed = await sm_db.sweep_orphan_fs_sessions()
            if removed:
                import structlog
                structlog.get_logger().info(
                    "orphan_session_dirs_swept", count=removed,
                )
        except Exception as e: # noqa: BLE001 — sweep 失敗不擋 startup
            import structlog
            structlog.get_logger().warning(
                "orphan_session_sweep_failed", error=str(e),
            )
    else:
        app.state.db_engine = None
        app.state.session_manager = SessionManager()

    app.state.llm_provider = _provider_from_env()

    # 全域 HookRegistry(routes / chat 用,讓 plugin / settings 註冊到此)
    hooks = HookRegistry()
    app.state.hooks = hooks
    await hooks.fire(SetupEvent(session_id=None, user_id=None))

    # 背景 scheduler(只在有 DB 時起;cron 到點以擁有者身分自動跑一輪)。
    # ORION_DISABLE_SCHEDULER=1 可關(測試 / 不想要背景 turn 時)。
    scheduler = None
    if db_engine is not None and os.environ.get("ORION_DISABLE_SCHEDULER") != "1":
        from orion_chat_api.scheduler import SchedulerEngine

        scheduler = SchedulerEngine(app)
        app.state.scheduler = scheduler
        try:
            await scheduler.start()
        except Exception:  # noqa: BLE001 — scheduler 起不來不擋 server
            import structlog

            structlog.get_logger().warning("scheduler_start_failed")
            scheduler = None

    try:
        yield
    finally:
        if scheduler is not None:
            with suppress(Exception):
                await scheduler.stop()
        if db_engine is not None:
            await db_engine.dispose()


def create_app() -> FastAPI:
    """工廠 — uvicorn 入口 / 測試用。"""
    app = FastAPI(
        title="orion-agent",
        version="0.1.0",
        description=(
            "Multi-LLM agent harness FastAPI layer. "
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

    # request_id middleware(每 request 產 UUID,bind structlog contextvars)
    app.middleware("http")(request_id_middleware)

    app.include_router(health_router.router)
    app.include_router(auth_router.router)
    app.include_router(sessions_router.router)
    app.include_router(uploads_router.router)
    app.include_router(preferences_router.router)
    app.include_router(user_settings_router.router)
    app.include_router(memories_router.router)
    app.include_router(skills_router.router)
    app.include_router(roles_router.router)
    app.include_router(soul_router.router)
    app.include_router(plan_router.router)
    app.include_router(projects_router.router)
    app.include_router(mcp_router.router)
    app.include_router(schedules_router.router)
    app.include_router(voice_router.router)
    app.include_router(collaborations_router.router)
    app.include_router(oauth_router.router)
    app.include_router(chat_router.router)

    return app


# Module-level app 給 `uvicorn orion_chat_api.app:app` 用
app = create_app()
