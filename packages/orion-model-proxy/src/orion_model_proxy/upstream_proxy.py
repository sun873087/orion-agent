"""Transparent reverse proxy 給外部 SDK 用 — Phase 31-X.3。

兩條對應路徑:
    /openai/{path:path}    → https://api.openai.com/{path}
    /anthropic/{path:path} → https://api.anthropic.com/{path}

外部 client(OpenAI / Anthropic SDK / curl / LangChain / 任何用 OpenAI 或
Anthropic wire format 的東西)指 `base_url` 過來,proxy 換掉 auth header
(proxy 自己保管真實 key),其他 headers / body / query / streaming SSE
全部 byte-for-byte 透傳。

跟 `/v1/messages`(Orion-native NormalizedMessage)的差別:
- /v1/* = 自家 host 走 orion_model 用,wire 是 NormalizedEvent NDJSON
- /openai/* + /anthropic/* = 外部 SDK 直接 work,wire 是 OpenAI / Anthropic
  各自原生格式,**proxy 不解析**,純 reverse
"""

from __future__ import annotations

import os
from typing import Iterable

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse


# Hop-by-hop headers — 不該透傳給 client(RFC 7230 §6.1)。
# 額外加 content-encoding / content-length 因為 httpx 解過 gzip 後 length 已變
# 真實 streaming chunks。
_HOP_BY_HOP_REQ = frozenset({
    "host", "connection", "keep-alive", "proxy-connection",
    "te", "trailer", "transfer-encoding", "upgrade",
    "authorization", "x-api-key",  # 永遠改寫(換 proxy 的 key)
    "content-length",  # httpx 會重算
})

_HOP_BY_HOP_RESP = frozenset({
    "connection", "keep-alive", "proxy-connection",
    "te", "trailer", "transfer-encoding", "upgrade",
    "content-encoding", "content-length",  # httpx 已 decode
})


def _filter_request_headers(
    headers: Iterable[tuple[str, str]],
) -> dict[str, str]:
    return {
        k: v
        for k, v in headers
        if k.lower() not in _HOP_BY_HOP_REQ
    }


def _filter_response_headers(headers: httpx.Headers) -> dict[str, str]:
    return {
        k: v
        for k, v in headers.items()
        if k.lower() not in _HOP_BY_HOP_RESP
    }


async def reverse_proxy(
    req: Request,
    path: str,
    *,
    upstream_base: str,
    auth_header: str,
    auth_value: str,
) -> StreamingResponse:
    """Transparent reverse proxy:把 req 完整 forward 給 upstream,response
    streaming 透回。

    Args:
        req: FastAPI Request
        path: catch-all path 部分,e.g. "v1/chat/completions"
        upstream_base: e.g. "https://api.openai.com"
        auth_header: client 端傳什麼都被覆蓋,e.g. "Authorization"
        auth_value: proxy 端用的真實 token,e.g. "Bearer sk-..."
    """
    target_url = f"{upstream_base.rstrip('/')}/{path.lstrip('/')}"
    body = await req.body()
    headers = _filter_request_headers(req.headers.items())
    headers[auth_header] = auth_value
    params = dict(req.query_params)

    # 打開 long-lived client + send streaming — 必須在 generator 外 send
    # 才拿得到 status_code / headers 給 StreamingResponse,但 client 生命週期
    # 要在 generator 結束才能 close。用 finally 處理。
    client = httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0))
    try:
        request = client.build_request(
            req.method,
            target_url,
            content=body if body else None,
            headers=headers,
            params=params,
        )
        upstream_resp = await client.send(request, stream=True)
    except httpx.HTTPError as e:
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"upstream connection failed: {e}") from e

    async def _passthrough():
        try:
            # aiter_bytes():httpx 自動 gzip/deflate decompress,
            # 跟 _filter_response_headers 拿掉 content-encoding 對齊。
            # aiter_raw() 會回壓縮過的 bytes,client 看 header 沒 encoding 就崩。
            async for chunk in upstream_resp.aiter_bytes():
                if chunk:
                    yield chunk
        finally:
            await upstream_resp.aclose()
            await client.aclose()

    return StreamingResponse(
        _passthrough(),
        status_code=upstream_resp.status_code,
        headers=_filter_response_headers(upstream_resp.headers),
        media_type=upstream_resp.headers.get("content-type"),
    )


def _require_key(env_var: str, provider_label: str) -> str:
    key = os.environ.get(env_var)
    if not key:
        raise HTTPException(
            status_code=503,
            detail=f"{env_var} not configured on proxy (refusing {provider_label} forward)",
        )
    return key


async def openai_reverse_proxy(req: Request, path: str) -> StreamingResponse:
    """OpenAI 用 Authorization: Bearer。"""
    key = _require_key("OPENAI_API_KEY", "OpenAI")
    return await reverse_proxy(
        req, path,
        upstream_base="https://api.openai.com",
        auth_header="Authorization",
        auth_value=f"Bearer {key}",
    )


async def anthropic_reverse_proxy(req: Request, path: str) -> StreamingResponse:
    """Anthropic 用 x-api-key header(不是 Bearer)。anthropic-version 也要透傳
    (client 端帶就 OK,不必我們設預設)。"""
    key = _require_key("ANTHROPIC_API_KEY", "Anthropic")
    return await reverse_proxy(
        req, path,
        upstream_base="https://api.anthropic.com",
        auth_header="x-api-key",
        auth_value=key,
    )


__all__ = ["anthropic_reverse_proxy", "openai_reverse_proxy", "reverse_proxy"]
