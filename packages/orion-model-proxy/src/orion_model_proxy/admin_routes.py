"""Admin REST + Web UI routes。

REST:
    POST   /admin/users
    GET    /admin/users
    DELETE /admin/users/{user_id}
    POST   /admin/users/{user_id}/keys           gen new(回明文一次)
    DELETE /admin/keys/{key_id}                  revoke
    POST   /admin/users/{user_id}/budget         set cap
    GET    /admin/users/{user_id}/usage          rollup

Web UI(Jinja2):/admin/ui/* — 在 server.py mount。

Auth:每個 endpoint 都 `Depends(require_admin)`(沒 admin token 401)。
"""

from __future__ import annotations

import secrets
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from orion_model_proxy.auth import (
    generate_token,
    hash_token,
    invalidate_cache,
    prefix_for_display,
    require_admin,
)
from orion_model_proxy.db import session as db_session
from orion_model_proxy.models import ApiKey, UsageLog, User


router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


# ─── DTOs ────────────────────────────────────────────────────────────────


class CreateUserRequest(BaseModel):
    email: EmailStr
    display_name: str | None = None
    budget_usd: float | None = None


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str | None
    budget_usd: float | None
    created_at: int
    monthly_cost_usd: float = 0.0


class CreateKeyRequest(BaseModel):
    label: str | None = None
    env: str = "prod"


class CreateKeyResponse(BaseModel):
    id: str
    user_id: str
    label: str | None
    token: str = Field(..., description="明文 token — 只在 create 時回一次")
    token_prefix: str
    created_at: int


class KeyOut(BaseModel):
    id: str
    user_id: str
    label: str | None
    token_prefix: str
    created_at: int
    last_used_at: int | None
    revoked_at: int | None


class SetBudgetRequest(BaseModel):
    budget_usd: float | None  # None = 取消 cap


class UsageRollup(BaseModel):
    user_id: str
    from_ts: int
    to_ts: int
    total_cost_usd: float
    by_model: dict[str, float]
    request_count: int


# ─── Users ────────────────────────────────────────────────────────────────


def _new_id() -> str:
    return secrets.token_hex(16)


def _now() -> int:
    return int(time.time())


async def _user_to_out(s: AsyncSession, user: User) -> UserOut:
    """User row + 當月 cost rollup。"""
    first_of_month = _first_of_month_ts()
    stmt = (
        select(func.coalesce(func.sum(UsageLog.cost_usd), 0.0))
        .where(UsageLog.user_id == user.id)
        .where(UsageLog.ts >= first_of_month)
    )
    monthly = float((await s.execute(stmt)).scalar() or 0.0)
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        budget_usd=user.budget_usd,
        created_at=user.created_at,
        monthly_cost_usd=monthly,
    )


def _first_of_month_ts() -> int:
    """當月 1 日 00:00 local epoch。"""
    import datetime as dt

    now = dt.datetime.now(dt.timezone.utc).astimezone()
    first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return int(first.timestamp())


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(
    req: CreateUserRequest, s: AsyncSession = Depends(db_session)
) -> UserOut:
    existing = (
        await s.execute(select(User).where(User.email == req.email))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"email {req.email} already exists")
    user = User(
        id=_new_id(),
        email=req.email,
        display_name=req.display_name,
        budget_usd=req.budget_usd,
        created_at=_now(),
    )
    s.add(user)
    await s.commit()
    await s.refresh(user)
    return await _user_to_out(s, user)


@router.get("/users", response_model=list[UserOut])
async def list_users(s: AsyncSession = Depends(db_session)) -> list[UserOut]:
    users = (await s.execute(select(User).order_by(User.created_at.desc()))).scalars().all()
    return [await _user_to_out(s, u) for u in users]


@router.get("/users/{user_id}", response_model=UserOut)
async def get_user(user_id: str, s: AsyncSession = Depends(db_session)) -> UserOut:
    user = await s.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"user {user_id} not found")
    return await _user_to_out(s, user)


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: str, s: AsyncSession = Depends(db_session)) -> None:
    user = await s.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"user {user_id} not found")
    await s.delete(user)
    await s.commit()
    await invalidate_cache(None)  # flush cache,可能 user 的 key 還在


# ─── Keys ────────────────────────────────────────────────────────────────


@router.post("/users/{user_id}/keys", response_model=CreateKeyResponse, status_code=201)
async def create_key(
    user_id: str,
    req: CreateKeyRequest,
    s: AsyncSession = Depends(db_session),
) -> CreateKeyResponse:
    user = await s.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"user {user_id} not found")
    plaintext = generate_token(env=req.env)
    key = ApiKey(
        id=_new_id(),
        user_id=user.id,
        token_hash=hash_token(plaintext),
        token_prefix=prefix_for_display(plaintext),
        label=req.label,
        created_at=_now(),
    )
    s.add(key)
    await s.commit()
    await s.refresh(key)
    return CreateKeyResponse(
        id=key.id,
        user_id=key.user_id,
        label=key.label,
        token=plaintext,  # 唯一一次回明文
        token_prefix=key.token_prefix,
        created_at=key.created_at,
    )


@router.get("/users/{user_id}/keys", response_model=list[KeyOut])
async def list_keys(
    user_id: str, s: AsyncSession = Depends(db_session)
) -> list[KeyOut]:
    user = await s.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"user {user_id} not found")
    keys = (
        await s.execute(
            select(ApiKey)
            .where(ApiKey.user_id == user_id)
            .order_by(ApiKey.created_at.desc())
        )
    ).scalars().all()
    return [
        KeyOut(
            id=k.id,
            user_id=k.user_id,
            label=k.label,
            token_prefix=k.token_prefix,
            created_at=k.created_at,
            last_used_at=k.last_used_at,
            revoked_at=k.revoked_at,
        )
        for k in keys
    ]


@router.delete("/keys/{key_id}", status_code=204)
async def revoke_key(key_id: str, s: AsyncSession = Depends(db_session)) -> None:
    key = await s.get(ApiKey, key_id)
    if key is None:
        raise HTTPException(status_code=404, detail=f"key {key_id} not found")
    if key.revoked_at is not None:
        return  # 已 revoked,idempotent
    await s.execute(
        update(ApiKey).where(ApiKey.id == key_id).values(revoked_at=_now())
    )
    await s.commit()
    await invalidate_cache(key.token_hash)


# ─── Budget ──────────────────────────────────────────────────────────────


@router.post("/users/{user_id}/budget", response_model=UserOut)
async def set_budget(
    user_id: str,
    req: SetBudgetRequest,
    s: AsyncSession = Depends(db_session),
) -> UserOut:
    user = await s.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"user {user_id} not found")
    user.budget_usd = req.budget_usd
    await s.commit()
    await s.refresh(user)
    await invalidate_cache(None)  # principal cache 帶 budget,得 refresh
    return await _user_to_out(s, user)


# ─── Usage ───────────────────────────────────────────────────────────────


@router.get("/users/{user_id}/usage", response_model=UsageRollup)
async def get_usage(
    user_id: str,
    from_ts: int | None = None,
    to_ts: int | None = None,
    s: AsyncSession = Depends(db_session),
) -> UsageRollup:
    user = await s.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"user {user_id} not found")
    if from_ts is None:
        from_ts = _first_of_month_ts()
    if to_ts is None:
        to_ts = _now()

    base = (
        select(UsageLog)
        .where(UsageLog.user_id == user_id)
        .where(UsageLog.ts >= from_ts)
        .where(UsageLog.ts <= to_ts)
    )
    rows = (await s.execute(base)).scalars().all()
    total = sum(r.cost_usd for r in rows)
    by_model: dict[str, float] = {}
    for r in rows:
        by_model[r.model] = by_model.get(r.model, 0.0) + r.cost_usd
    return UsageRollup(
        user_id=user_id,
        from_ts=from_ts,
        to_ts=to_ts,
        total_cost_usd=round(total, 6),
        by_model={m: round(c, 6) for m, c in by_model.items()},
        request_count=len(rows),
    )


__all__ = ["router"]
