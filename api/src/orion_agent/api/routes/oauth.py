"""/oauth/* — Phase 25。MCP OAuth web flow。

  POST   /oauth/start              {server} → {authorize_url, state}
  GET    /oauth/callback           ?state&code → HTML close-window
  GET    /oauth/status/{server}    → {connected, available, label}
  GET    /oauth/providers          list providers
  DELETE /oauth/{server}           解除連線(刪 SecureStorage)

callback 是 query-string GET,跟其他 endpoint 不同 — 因為是第三方 redirect 過來,
**不能**要求 Authorization header(瀏覽器 redirect 不會帶)。state token 充當
authorization:state 是 server 自己頒發的 short-lived token,綁了 user_id。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from starlette.requests import Request

from orion_agent.api.deps import current_user
from orion_agent.mcp import oauth as oauth_mod

router = APIRouter()


class StartBody(BaseModel):
    server: str


class StartResponse(BaseModel):
    authorize_url: str
    state: str


class StatusResponse(BaseModel):
    server: str
    label: str
    available: bool
    connected: bool


class ProviderInfo(BaseModel):
    name: str
    label: str
    available: bool


def _redirect_uri(request: Request) -> str:
    """callback URL — 用實際 host(本機 dev 8000、production 換 reverse proxy)。"""
    base = str(request.base_url).rstrip("/")
    return f"{base}/oauth/callback"


@router.get("/oauth/providers", response_model=list[ProviderInfo])
async def list_providers(
    _user_id: Annotated[str, Depends(current_user)],
) -> list[ProviderInfo]:
    """所有 known providers(含 unavailable);UI list 用。"""
    return [
        ProviderInfo(name=p.name, label=p.label, available=p.available())
        for p in oauth_mod.list_providers()
    ]


@router.post("/oauth/start", response_model=StartResponse)
async def start_oauth(
    body: StartBody,
    request: Request,
    user_id: Annotated[str, Depends(current_user)],
) -> StartResponse:
    try:
        url, state = await oauth_mod.start_web_oauth_flow(
            body.server, user_id, redirect_uri=_redirect_uri(request),
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return StartResponse(authorize_url=url, state=state)


_CALLBACK_OK_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Connected</title></head>
<body style="font-family:system-ui,-apple-system,sans-serif;
             padding:48px;text-align:center;color:#262624;">
  <h2 style="margin:0 0 8px">✓ Connected to {server}</h2>
  <p style="color:#797772;margin:0">You can close this window.</p>
  <script>setTimeout(function(){{ window.close(); }}, 800);</script>
</body></html>"""

_CALLBACK_ERR_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>OAuth error</title></head>
<body style="font-family:system-ui,-apple-system,sans-serif;
             padding:48px;text-align:center;color:#262624;">
  <h2 style="margin:0 0 8px;color:#cc785c">OAuth failed</h2>
  <p style="color:#797772;margin:0">{message}</p>
</body></html>"""


@router.get("/oauth/callback", response_class=HTMLResponse)
async def callback(
    state: Annotated[str, Query(...)],
    code: Annotated[str, Query(...)],
) -> HTMLResponse:
    """第三方 redirect 進來(GET、query string)。state token 充當 user 證明。"""
    try:
        server = await oauth_mod.handle_oauth_callback(state, code)
    except ValueError as e:
        return HTMLResponse(
            _CALLBACK_ERR_HTML.format(message=str(e)),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return HTMLResponse(_CALLBACK_OK_HTML.format(server=server))


@router.get("/oauth/status/{server}", response_model=StatusResponse)
async def get_status(
    server: str,
    user_id: Annotated[str, Depends(current_user)],
) -> StatusResponse:
    provider = oauth_mod.get_provider(server)
    if provider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown provider {server!r}")
    return StatusResponse(
        server=provider.name,
        label=provider.label,
        available=provider.available(),
        connected=await oauth_mod.is_connected(server, user_id),
    )


@router.delete("/oauth/{server}")
async def disconnect(
    server: str,
    user_id: Annotated[str, Depends(current_user)],
) -> dict[str, bool]:
    if oauth_mod.get_provider(server) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown provider {server!r}")
    await oauth_mod.disconnect(server, user_id)
    return {"disconnected": True}
