"""FastAPI service — transparent reverse proxy to OpenAI / Anthropic。

簡化後架構(Phase 31-X.4)— 只有兩條 wire,都是 native:

    /openai/{path:path}     → https://api.openai.com/{path}
    /anthropic/{path:path}  → https://api.anthropic.com/{path}

Proxy 對外:換 auth header,其他全 byte-for-byte 透傳。Streaming SSE 也透傳。

自家 host(orion_model.AnthropicProvider / OpenAIProvider)走 SDK 的 base_url
參數指這 endpoint,跟外部 SDK / 工具(LangChain / Cursor / aider)用法一致。
**proxy 不再有 Orion-native /v1/messages 中間層**(冗餘,SDK 自己會 wire)。

Auth:`ORION_MODEL_PROXY_KEY` env 設了時要求 Bearer header;沒設 = 不認證
(本機 dev)。
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# auto_error=False:讓 missing header 走我們自己的 401(才能跟 env 沒設時
# 的 skip 邏輯共存)。description 在 Swagger UI 的 Authorize dialog 出現。
_bearer_scheme = HTTPBearer(
    auto_error=False,
    description=(
        "Bearer token = ORION_MODEL_PROXY_KEY env on server. "
        "Leave blank if server didn't set the key (local dev mode)."
    ),
)


def require_auth(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> None:
    """env 沒設 → skip(本機 dev);設了 → 必須帶對的 Bearer。

    用 FastAPI `Depends` 而非手寫 header 解析,Swagger UI 才能從 OpenAPI
    `security` schema 長出 🔒 icon + 右上 Authorize 按鈕。
    """
    expected = os.environ.get("ORION_MODEL_PROXY_KEY")
    if not expected:
        return
    if creds is None:
        raise HTTPException(status_code=401, detail="missing Bearer token")
    if creds.credentials != expected:
        raise HTTPException(status_code=403, detail="invalid token")


def create_app() -> FastAPI:
    app = FastAPI(
        title="orion-model-proxy",
        version="0.2.0",
        description=(
            "Transparent reverse proxy to OpenAI / Anthropic. "
            "External SDKs set base_url to /openai/v1 or /anthropic and use as-is."
        ),
    )

    @app.get("/v1/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "providers": {
                "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
                "openai": bool(os.environ.get("OPENAI_API_KEY")),
            },
        }

    @app.get("/v1/catalog")
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

    @app.get("/v1/health/{provider}")
    async def health_per_provider(provider: str) -> JSONResponse:
        if provider == "anthropic":
            ok = bool(os.environ.get("ANTHROPIC_API_KEY"))
        elif provider == "openai":
            ok = bool(os.environ.get("OPENAI_API_KEY"))
        else:
            raise HTTPException(status_code=404, detail=f"unknown provider {provider!r}")
        return JSONResponse({"provider": provider, "ok": ok})

    # ─── Transparent reverse proxy(全部 chat / responses / audio / embeddings
    #     / files / 任何 OpenAI 未來新加 endpoint 自動支援)─────────────────
    from orion_model_proxy.upstream_proxy import (
        anthropic_reverse_proxy,
        openai_reverse_proxy,
    )

    @app.api_route(
        "/openai/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        dependencies=[Depends(require_auth)],
    )
    async def openai_compat(req: Request, path: str) -> StreamingResponse:
        return await openai_reverse_proxy(req, path)

    @app.api_route(
        "/anthropic/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        dependencies=[Depends(require_auth)],
    )
    async def anthropic_compat(req: Request, path: str) -> StreamingResponse:
        return await anthropic_reverse_proxy(req, path)

    return app
