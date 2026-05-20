"""Bearer token auth — DB-based lookup with in-process cache。

Token format:`sk-orion-<env>-<random_urlsafe_32>`,DB 存 `sha256(plaintext)` 而非
明文。Cache TTL 60s,admin revoke 時主動 invalidate。
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
import time
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orion_model_proxy.db import session as db_session
from orion_model_proxy.models import ApiKey, User


# ─── Token generation ─────────────────────────────────────────────────────


def generate_token(env: str = "prod") -> str:
    """`sk-orion-prod-<32 bytes urlsafe>` — admin issue 給 user 時呼一次。"""
    if not env or not env.replace("_", "").replace("-", "").isalnum():
        raise ValueError(f"invalid env tag: {env!r}")
    return f"sk-orion-{env}-{secrets.token_urlsafe(32)}"


def hash_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def prefix_for_display(plaintext: str) -> str:
    """`sk-orion-prod-9f3c...` — 給 admin UI 認自己 key 用,不洩明文。"""
    # 取到 random 段前 4 char 為止
    parts = plaintext.split("-", 3)
    if len(parts) < 4:
        return plaintext[:20]
    return f"{parts[0]}-{parts[1]}-{parts[2]}-{parts[3][:4]}"


# ─── In-process cache ────────────────────────────────────────────────────


@dataclass
class AuthedPrincipal:
    user_id: str
    api_key_id: str
    email: str
    budget_usd: float | None
    rate_limit_rpm: int | None = None


_TTL_SECONDS = 60
_cache: dict[str, tuple[AuthedPrincipal, float]] = {}
_cache_lock = asyncio.Lock()


def _now() -> float:
    return time.time()


async def invalidate_cache(token_hash: Optional[str] = None) -> None:
    """admin revoke / delete user 時呼。token_hash None → flush 全部。"""
    async with _cache_lock:
        if token_hash is None:
            _cache.clear()
        else:
            _cache.pop(token_hash, None)


async def _lookup_db(
    s: AsyncSession, token_hash: str
) -> AuthedPrincipal | None:
    """Single SELECT join api_keys × users。revoked / unknown → None。"""
    stmt = (
        select(ApiKey, User)
        .join(User, ApiKey.user_id == User.id)
        .where(ApiKey.token_hash == token_hash)
        .where(ApiKey.revoked_at.is_(None))
    )
    row = (await s.execute(stmt)).first()
    if row is None:
        return None
    api_key, user = row
    return AuthedPrincipal(
        user_id=user.id,
        api_key_id=api_key.id,
        email=user.email,
        budget_usd=user.budget_usd,
        rate_limit_rpm=user.rate_limit_rpm,
    )


async def _is_revoked(s: AsyncSession, token_hash: str) -> bool:
    """Token hash 存在但 revoked_at 非空 → True。
    用來區分「沒身分(401)」vs「曾有但被撤(403)」。"""
    stmt = (
        select(ApiKey.revoked_at)
        .where(ApiKey.token_hash == token_hash)
        .where(ApiKey.revoked_at.is_not(None))
    )
    return (await s.execute(stmt)).scalar() is not None


async def _lookup_cached_or_db(
    s: AsyncSession, token_hash: str
) -> AuthedPrincipal | None:
    now = _now()
    async with _cache_lock:
        cached = _cache.get(token_hash)
        if cached is not None and (now - cached[1]) < _TTL_SECONDS:
            return cached[0]
    principal = await _lookup_db(s, token_hash)
    if principal is not None:
        async with _cache_lock:
            _cache[token_hash] = (principal, now)
    return principal


# ─── FastAPI Depends ─────────────────────────────────────────────────────


_bearer_scheme = HTTPBearer(
    auto_error=False,
    description="Bearer = your sk-orion-<env>-... token.",
)


async def require_auth(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    s: AsyncSession = Depends(db_session),
) -> AuthedPrincipal:
    """Multi-tenant DB lookup。Phase 32 後唯一 auth path。

    對齊 OpenAI / Anthropic 的 status code 慣例:
        401 Unauthorized = 無身分(沒帶 / 格式錯 / 不在 DB)→ SDK AuthenticationError
        403 Forbidden    = 有身分但無權(已 revoked)→ SDK PermissionDeniedError
    """
    if creds is None:
        raise HTTPException(status_code=401, detail="missing Bearer token")
    token = creds.credentials
    if not token.startswith("sk-orion-"):
        raise HTTPException(status_code=401, detail="invalid API key format")
    token_hash = hash_token(token)
    # 先看「曾經存在但被 revoke」(403)再 fallback「完全不認識」(401)
    revoked = await _is_revoked(s, token_hash)
    if revoked:
        raise HTTPException(status_code=403, detail="API key has been revoked")
    principal = await _lookup_cached_or_db(s, token_hash)
    if principal is None:
        raise HTTPException(status_code=401, detail="invalid API key")

    # last_used_at 非同步背景 update — 不阻塞 request
    asyncio.create_task(_touch_last_used(principal.api_key_id))
    request.state.principal = principal
    return principal


async def _touch_last_used(api_key_id: str) -> None:
    """背景更新 last_used_at — 失敗 swallow,不阻塞 request。"""
    from orion_model_proxy.db import get_session_factory

    try:
        factory = get_session_factory()
        async with factory() as s:
            from sqlalchemy import update

            await s.execute(
                update(ApiKey).where(ApiKey.id == api_key_id).values(last_used_at=int(_now()))
            )
            await s.commit()
    except Exception:  # noqa: BLE001 — best-effort
        pass


# ─── Admin auth ──────────────────────────────────────────────────────────


_admin_bearer = HTTPBearer(
    auto_error=False, description="Admin Bearer = ORION_MODEL_PROXY_ADMIN_KEY env."
)


async def require_admin(
    creds: HTTPAuthorizationCredentials | None = Depends(_admin_bearer),
) -> None:
    """簡單 env 比對 — admin 是 single secret,不存 DB。"""
    expected = os.environ.get("ORION_MODEL_PROXY_ADMIN_KEY")
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="ORION_MODEL_PROXY_ADMIN_KEY not configured on server",
        )
    if creds is None or creds.credentials != expected:
        raise HTTPException(status_code=401, detail="invalid admin token")


async def enforce_budget(request: Request) -> None:
    """Phase X.3 — pre-request:user 累計成本 >= budget cap → 402。

    Pre-request 不知這次 request 會花多少,所以是「已超 cap 才擋下一次」。
    最後一次可能略過 cap,文件已說明。
    """
    principal: AuthedPrincipal | None = getattr(request.state, "principal", None)
    if principal is None or principal.budget_usd is None:
        return  # no cap

    from orion_model_proxy.usage_logger import get_running_cost

    running = await get_running_cost(principal.user_id)
    if running >= principal.budget_usd:
        raise HTTPException(
            status_code=402,
            detail=(
                f"budget cap reached: ${running:.4f} >= ${principal.budget_usd:.4f}. "
                f"Contact admin to raise the cap."
            ),
        )


async def enforce_rate_limit(request: Request) -> None:
    """Phase 33-B — pre-request rate limit。RPM 沒設或 0 → 不擋。"""
    principal: AuthedPrincipal | None = getattr(request.state, "principal", None)
    if principal is None or not principal.rate_limit_rpm:
        return
    from orion_model_proxy.rate_limit import check_and_consume

    ok = await check_and_consume(principal.user_id, principal.rate_limit_rpm)
    if not ok:
        raise HTTPException(
            status_code=429,
            detail=(
                f"rate limit exceeded ({principal.rate_limit_rpm} req/min). "
                f"Retry after a few seconds."
            ),
        )


__all__ = [
    "AuthedPrincipal",
    "enforce_budget",
    "enforce_rate_limit",
    "generate_token",
    "hash_token",
    "invalidate_cache",
    "prefix_for_display",
    "require_admin",
    "require_auth",
]
