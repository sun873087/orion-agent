"""FastAPI service — transparent reverse proxy to OpenAI / Anthropic。4(transparent reverse)+(multi-tenant + DB + admin + 計費)。

Endpoints:
    /openai/{path:path} → https://api.openai.com/{path}
    /anthropic/{path:path} → https://api.anthropic.com/{path}
    /v1/health[/{provider}] / /v1/catalog
    /admin/* multi-tenant CRUD + usage rollup
    /admin/ui/* server-rendered web UI

Auth(唯一模式):
- 多租戶:Bearer token 走 sha256 DB lookup,token 由 admin 透過 REST / UI 生成
- Admin 自己用 `ORION_MODEL_PROXY_ADMIN_KEY` env(獨立)— 沒設 admin endpoints 503
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse, StreamingResponse

from orion_model_proxy.auth import enforce_budget, enforce_rate_limit, require_auth


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Startup:init DB(create_all idempotent)。後 multi-tenant 是唯一模式。"""
    from orion_model_proxy.db import init_db
    await init_db()
    yield


_OPENAPI_TAGS = [
    {
        "name": "health",
        "description": "Health probe + Orion catalog metadata。Public, no auth。",
    },
    {
        "name": "openai",
        "description": (
            "Transparent reverse proxy → api.openai.com。catch-all `/openai/{path}` "
            "支援 GET/POST/PUT/PATCH/DELETE,任何 OpenAI endpoint 都會自動 work。"
            "Auth:user Bearer `sk-orion-...`。Budget cap 達 → 402。"
        ),
    },
    {
        "name": "anthropic",
        "description": (
            "Transparent reverse proxy → api.anthropic.com。catch-all "
            "`/anthropic/{path}` 全 verb 支援。同 OpenAI 的 auth + budget。"
        ),
    },
    {
        "name": "admin",
        "description": (
            "Admin REST — multi-tenant CRUD(users / keys / budget / usage rollup)。"
            "Auth: `ORION_MODEL_PROXY_ADMIN_KEY` env Bearer。"
        ),
    },
    {
        "name": "admin-ui",
        "description": (
            "Admin Web UI(Jinja2 server-rendered)。 Login 完成後存 HttpOnly "
            "cookie,後續頁面靠 cookie 而非每次帶 Bearer。"
        ),
    },
]


def create_app() -> FastAPI:
    app = FastAPI(
        title="orion-model-proxy",
        version="0.3.0",
        description=(
            "Transparent reverse proxy to OpenAI / Anthropic with multi-tenant "
            "auth + per-user cost tracking. External SDKs set base_url to /openai/v1 "
            "or /anthropic and use as-is."
        ),
        openapi_tags=_OPENAPI_TAGS,
        lifespan=_lifespan,
    )

    # Admin routes(REST + Web UI)永遠掛上(多租戶為唯一模式)。
    from orion_model_proxy.admin_routes import router as admin_router
    from orion_model_proxy.admin_ui import router as admin_ui_router
    app.include_router(admin_router)
    app.include_router(admin_ui_router)

    @app.get("/v1/health", tags=["health"])
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "providers": {
                "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
                "openai": bool(os.environ.get("OPENAI_API_KEY")),
            },
        }

    @app.get("/v1/catalog", tags=["health"])
    async def catalog() -> dict[str, Any]:
        """Orion catalog(chat / stt / tts metadata)。

        Host 端設 ORION_MODEL_PROXY_URL 後,orion_model.{catalog,stt_catalog,
        tts_catalog} 內部 list_*() 函式會 fetch 這個 endpoint(同 process 內
        cache),不再直接讀本地 packaged json — 確保**唯一 source of truth 在
        proxy**(將來 routing alias / pricing 變更等都先改 proxy)。

        Proxy 不可達 / fetch 失敗時 host 自動 fallback 到 packaged json,
        保持 dev / CI 不必先起 proxy daemon 的 ergonomics。
        """
        from orion_model.catalog import list_catalog
        from orion_model.stt_catalog import list_stt_catalog
        from orion_model.tts_catalog import list_tts_catalog
        return {
            "chat": list_catalog(),
            "stt": list_stt_catalog(),
            "tts": list_tts_catalog(),
        }

    @app.get("/v1/health/{provider}", tags=["health"])
    async def health_per_provider(provider: str) -> JSONResponse:
        if provider == "anthropic":
            ok = bool(os.environ.get("ANTHROPIC_API_KEY"))
        elif provider == "openai":
            ok = bool(os.environ.get("OPENAI_API_KEY"))
        else:
            raise HTTPException(status_code=404, detail=f"unknown provider {provider!r}")
        return JSONResponse({"provider": provider, "ok": ok})

    # ─── Transparent reverse proxy(全部 chat / responses / audio / embeddings
    # / files / 任何 OpenAI 未來新加 endpoint 自動支援)─────────────────
    from orion_model_proxy.upstream_proxy import (
        anthropic_reverse_proxy,
        openai_reverse_proxy,
    )

    @app.api_route(
        "/openai/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        dependencies=[Depends(require_auth), Depends(enforce_rate_limit), Depends(enforce_budget)],
        tags=["openai"],
    )
    async def openai_compat(req: Request, path: str) -> StreamingResponse:
        return await openai_reverse_proxy(req, path)

    @app.api_route(
        "/anthropic/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        dependencies=[Depends(require_auth), Depends(enforce_rate_limit), Depends(enforce_budget)],
        tags=["anthropic"],
    )
    async def anthropic_compat(req: Request, path: str) -> StreamingResponse:
        return await anthropic_reverse_proxy(req, path)

    # E:OpenAI Realtime WebSocket pass-through 骨架。實作未完成 —
    # 主要 use case 是 voice。先註冊 endpoint + 503,避免 path 撞到 catch-all。
    @app.websocket("/openai/v1/realtime")
    async def openai_realtime_ws(ws: WebSocket) -> None:
        await ws.accept()
        await ws.send_json({
            "type": "error",
            "error": {
                "code": "NOT_IMPLEMENTED",
                "message": (
                    "WebSocket realtime proxy 尚未實作 skeleton。"
                    "目前只支援 HTTP /openai/{path}。"
                ),
            },
        })
        await ws.close(code=1000)

    return app
