"""JWT auth — Phase 6 dev mode。

對應 spec § 5 auth.py。

dev 規則:任意 username 可登入,server 簽發 24h JWT。Phase 7 換真 user DB / OAuth。

Secret:
- 從 ORION_JWT_SECRET 環境變數讀
- 沒設 → 起 server 時自動產 random(restart 後失效,只給 dev)
"""

from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pydantic import BaseModel, Field

_DEFAULT_TOKEN_HOURS = 24
_ALGORITHM = "HS256"


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)


class LoginResponse(BaseModel):
    token: str
    user_id: str
    expires_at: str  # ISO datetime


_runtime_secret: str | None = None


def _get_secret() -> str:
    """讀 / 產 JWT secret。"""
    global _runtime_secret
    raw = os.environ.get("ORION_JWT_SECRET")
    if raw:
        return raw
    # process-lifetime random — 只給 dev,restart 即失效
    if _runtime_secret is None:
        _runtime_secret = secrets.token_urlsafe(32)
    return _runtime_secret


def issue_token(username: str, *, hours: int = _DEFAULT_TOKEN_HOURS) -> LoginResponse:
    """簽發 JWT。dev 模式不檢查 username 是否合法,只要不空。"""
    now = datetime.now(UTC)
    exp = now + timedelta(hours=hours)
    payload = {
        "sub": username,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(payload, _get_secret(), algorithm=_ALGORITHM)
    return LoginResponse(
        token=token,
        user_id=username,
        expires_at=exp.isoformat(),
    )


def verify_token(token: str) -> str:
    """驗 JWT,回 user_id(sub)。失敗 raise jwt 例外。"""
    payload: dict[str, Any] = jwt.decode(
        token, _get_secret(), algorithms=[_ALGORITHM],
    )
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        raise jwt.InvalidTokenError("missing sub in token")
    return sub
