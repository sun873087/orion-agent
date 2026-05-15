"""JWT auth — Phase 29 之後:`sub` 一律為 user.id(UUID),`username` 走獨立 claim。

歷史:
- Phase 6 dev mode 直接把 username 放 sub。
- Phase 7 加 DB-backed login 但仍維持 sub=username。
- Phase 29 把 sub 改回 user.id,讓 schema 的 FK(指 users.id)真的對得起來。
  Dev fallback(無 DB)用 uuid5(NAMESPACE_DNS, username) deterministic 算 user_id,
  保證跨重啟 / 跨機器一致(同 username 永遠拿到同 uuid)。

Secret:
- 從 ORION_JWT_SECRET 環境變數讀
- 沒設 → 起 server 時自動產 random(restart 後失效,只給 dev)

Token rotation:
- 新 token 必含 `username` claim;舊 Phase 6/7 token 沒這欄 → `verify_token` 一律 401。
  等同強制所有 user 重 login(plan §3.4 的 token rotation 路徑 (b))。
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_DNS, uuid5

import jwt
from pydantic import BaseModel, Field

_DEFAULT_TOKEN_HOURS = 24
_ALGORITHM = "HS256"


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)


class LoginResponse(BaseModel):
    token: str
    user_id: str
    """user.id(UUID 字串)— Phase 29 後就是 DB 的 PK 而非 username。"""
    username: str
    expires_at: str  # ISO datetime


@dataclass(frozen=True, slots=True)
class Identity:
    """從 JWT 解出的身分。`user_id` 對應 sub(UUID);`username` 是顯示用名稱。"""

    user_id: str
    username: str


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


def dev_user_id(username: str) -> str:
    """Dev fallback:沒 DB 時用 uuid5 把 username 映射成 deterministic UUID。

    同 username 永遠拿到同 UUID — token 跨 server 重啟仍對得上。production 應用 DB。
    """
    return str(uuid5(NAMESPACE_DNS, username))


def issue_token(
    *,
    user_id: str,
    username: str,
    hours: int = _DEFAULT_TOKEN_HOURS,
) -> LoginResponse:
    """簽發 JWT。`sub` 放 user_id,額外 `username` claim 給 /me 等顯示用。"""
    now = datetime.now(UTC)
    exp = now + timedelta(hours=hours)
    payload = {
        "sub": user_id,
        "username": username,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(payload, _get_secret(), algorithm=_ALGORITHM)
    return LoginResponse(
        token=token,
        user_id=user_id,
        username=username,
        expires_at=exp.isoformat(),
    )


def verify_token_full(token: str) -> Identity:
    """驗 JWT 並回 Identity(user_id + username)。

    缺 `username` claim → InvalidTokenError(舊版 Phase 6/7 token 被拒,token rotation
    透過 schema 升級實作,不必換 secret)。
    """
    payload: dict[str, Any] = jwt.decode(
        token, _get_secret(), algorithms=[_ALGORITHM],
    )
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        raise jwt.InvalidTokenError("missing sub in token")
    username = payload.get("username")
    if not isinstance(username, str) or not username:
        # 舊版 token(Phase 6/7,sub=username 沒 username claim)— 強制重 login
        raise jwt.InvalidTokenError(
            "token missing 'username' claim — please re-login (token format upgraded)"
        )
    return Identity(user_id=sub, username=username)


def verify_token(token: str) -> str:
    """驗 JWT,回 user_id(sub)。失敗 raise jwt 例外。

    向後相容呼叫者:`current_user` / chat ws auth 仍只要 user_id 字串。
    完整身分用 `verify_token_full`。
    """
    return verify_token_full(token).user_id
