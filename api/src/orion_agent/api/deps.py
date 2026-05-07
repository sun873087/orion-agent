"""FastAPI dependencies — Auth、SessionManager、LLMProvider 注入。

對應 spec § 5 deps.py。
"""

from __future__ import annotations

import os
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.requests import HTTPConnection

from orion_agent.api.auth import verify_token
from orion_agent.api.session_manager import SessionManager
from orion_agent.llm.provider import LLMProvider, get_provider

_bearer = HTTPBearer(auto_error=True)


def _provider_from_env() -> LLMProvider:
    """從環境變數選 provider + model;CLI 可由 ORION_PROVIDER / ORION_MODEL 覆蓋。"""
    p = os.environ.get("ORION_PROVIDER", "anthropic")
    m = os.environ.get("ORION_MODEL", "claude-sonnet-4-6")
    return get_provider(p, m)


def get_session_manager(connection: HTTPConnection) -> SessionManager:
    """從 app.state 取 SessionManager(lifespan 內建立)。

    `HTTPConnection` 是 Request 與 WebSocket 的共同 base class — 兩種 route 都吃。
    """
    sm = getattr(connection.app.state, "session_manager", None)
    if sm is None:
        # 防呆:lifespan 沒跑(直接 TestClient 而沒進 with 區塊)→ 自動建
        sm = SessionManager()
        connection.app.state.session_manager = sm
    return sm


def get_llm_provider(connection: HTTPConnection) -> LLMProvider:
    """從 app.state 取 LLMProvider(lifespan 內建立);沒則臨時建。"""
    p = getattr(connection.app.state, "llm_provider", None)
    if p is None:
        p = _provider_from_env()
        connection.app.state.llm_provider = p
    return p


def current_user(
    creds: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> str:
    """從 Authorization: Bearer <token> 取出 user_id。失敗 → 401。"""
    try:
        return verify_token(creds.credentials)
    except jwt.ExpiredSignatureError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token expired") from e
    except jwt.InvalidTokenError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {e}") from e
