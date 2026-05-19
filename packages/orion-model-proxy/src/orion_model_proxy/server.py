"""FastAPI service — POST /v1/messages NDJSON streaming。

Wire format(Orion native):
    Request body (JSON):
        provider          str  ('anthropic' | 'openai' | 'ollama')
        model             str
        system            str | list[str]
        messages          list[NormalizedMessage]
        tools             list[ToolDefinition] | null
        max_tokens        int  (default 4096)
        temperature       float | null
        cache_breakpoints list[int] | null
        reasoning_effort  'minimal'|'low'|'medium'|'high' | null

    Response: application/x-ndjson — 每行一個 NormalizedEvent JSON。

Auth:`ORION_MODEL_PROXY_KEY` env 有設時,request 必須帶 Authorization:
Bearer {key} header。沒設 → 不認證(本機 / 內網 dev 用)。

Backend dispatch:直接 import orion_model.provider.get_provider — proxy 內
**不能再**走 env-gate proxy(避免無限迴圈),所以這邊用低階 import bypass。
"""

from __future__ import annotations

import json
import os
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from orion_model.catalog import list_catalog
from orion_model.tool_def import ToolDefinition
from orion_model.types import NormalizedMessage


def _direct_provider(provider_name: str, model: str):
    """Bypass env-gate get_provider — proxy 內呼真實 backend,不能再走 proxy。"""
    if provider_name == "anthropic":
        from orion_model.anthropic_provider import AnthropicProvider
        return AnthropicProvider(model=model)
    if provider_name == "openai":
        from orion_model.openai_provider import OpenAIProvider
        return OpenAIProvider(model=model)
    if provider_name == "ollama":
        from orion_model.ollama_provider import OllamaProvider
        return OllamaProvider(model=model)
    raise ValueError(f"unknown provider: {provider_name!r}")


class MessagesRequest(BaseModel):
    provider: Literal["anthropic", "openai", "ollama"]
    model: str
    system: str | list[str] = ""
    messages: list[NormalizedMessage] = Field(default_factory=list)
    tools: list[ToolDefinition] | None = None
    max_tokens: int = 4096
    temperature: float | None = None
    cache_breakpoints: list[int] | None = None
    reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None


def _check_auth(req: Request) -> None:
    """Bearer-token auth。`ORION_MODEL_PROXY_KEY` env 沒設 → skip(本機 dev)。"""
    expected = os.environ.get("ORION_MODEL_PROXY_KEY")
    if not expected:
        return
    auth = req.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing Bearer token")
    if auth[len("Bearer "):].strip() != expected:
        raise HTTPException(status_code=403, detail="invalid token")


def create_app() -> FastAPI:
    app = FastAPI(title="orion-model-proxy", version="0.1.0")

    @app.get("/v1/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "providers": {
                "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
                "openai": bool(os.environ.get("OPENAI_API_KEY")),
                "ollama": True,  # local 沒 key 概念,可達就有
            },
        }

    @app.get("/v1/models")
    async def models() -> dict[str, Any]:
        """Merged catalog — host /v1/models 對接 frontend model picker。"""
        return list_catalog()

    @app.post("/v1/messages")
    async def messages(req: Request) -> StreamingResponse:
        _check_auth(req)
        try:
            body = await req.json()
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"bad JSON: {e}") from e
        try:
            payload = MessagesRequest.model_validate(body)
        except Exception as e:  # noqa: BLE001 - pydantic validation
            raise HTTPException(status_code=422, detail=str(e)) from e

        try:
            provider = _direct_provider(payload.provider, payload.model)
        except (ValueError, RuntimeError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        async def _stream():
            try:
                async for ev in provider.stream(
                    system=payload.system,
                    messages=payload.messages,
                    tools=payload.tools,
                    max_tokens=payload.max_tokens,
                    temperature=payload.temperature,
                    cache_breakpoints=payload.cache_breakpoints,
                    reasoning_effort=payload.reasoning_effort,
                ):
                    line = json.dumps(ev.model_dump(mode="json"), ensure_ascii=False)
                    yield line + "\n"
            except Exception as e:  # noqa: BLE001
                err = {
                    "type": "error",
                    "message": f"{type(e).__name__}: {e}",
                }
                yield json.dumps(err, ensure_ascii=False) + "\n"

        return StreamingResponse(
            _stream(),
            media_type="application/x-ndjson",
        )

    # /v1/health/{provider} — per-provider ping(可選 — health 已 cover)
    @app.get("/v1/health/{provider}")
    async def health_per_provider(provider: str) -> JSONResponse:
        if provider == "anthropic":
            ok = bool(os.environ.get("ANTHROPIC_API_KEY"))
        elif provider == "openai":
            ok = bool(os.environ.get("OPENAI_API_KEY"))
        elif provider == "ollama":
            # 簡單 ping ollama /api/version
            try:
                from orion_model.ollama_provider import check_ollama_health
                result = await check_ollama_health()
                ok = bool(result.get("ok"))
            except Exception:  # noqa: BLE001
                ok = False
        else:
            raise HTTPException(status_code=404, detail=f"unknown provider {provider!r}")
        return JSONResponse({"provider": provider, "ok": ok})

    return app
