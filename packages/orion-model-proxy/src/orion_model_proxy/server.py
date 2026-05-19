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

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse


def _check_auth(req: Request) -> None:
    """Bearer-token auth。env 沒設 → skip(本機 dev)。"""
    expected = os.environ.get("ORION_MODEL_PROXY_KEY")
    if not expected:
        return
    auth = req.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing Bearer token")
    if auth[len("Bearer "):].strip() != expected:
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
        """Orion 自家 catalog(chat / stt / tts)— pricing / label /
        recommended / max_context_tokens / supports_reasoning。

        跟動態 `/openai/v1/models`(OpenAI native)或 `/anthropic/v1/models`
        並存:那是「OpenAI / Anthropic 現在 server 上能用什麼」,**這個是**
        「Orion 認可 + 帶元資料的子集」(外部 SDK / 工具想知道我們的推薦
        + 計費資訊用這個)。

        三段獨立:不是所有 model 都同時有 chat/stt/tts。
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
    )
    async def openai_compat(req: Request, path: str) -> StreamingResponse:
        _check_auth(req)
        return await openai_reverse_proxy(req, path)

    @app.api_route(
        "/anthropic/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    )
    async def anthropic_compat(req: Request, path: str) -> StreamingResponse:
        _check_auth(req)
        return await anthropic_reverse_proxy(req, path)

    return app
