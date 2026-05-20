"""Admin Web UI — server-rendered Jinja2,no JS state。

Session 走 HttpOnly cookie 存 admin token。Login form / users list / user
detail。所有 POST 都帶 CSRF-like 來源檢查就 OK(本機 admin tool,不上互聯網)。
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Cookie, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orion_model_proxy.auth import (
    generate_token,
    hash_token,
    invalidate_cache,
    prefix_for_display,
)
from orion_model_proxy.db import session as db_session
from orion_model_proxy.models import ApiKey, UsageLog, User


_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter(prefix="/admin/ui", tags=["admin-ui"])


_COOKIE_NAME = "orion_admin"


def _admin_token() -> str | None:
    return os.environ.get("ORION_MODEL_PROXY_ADMIN_KEY")


def _check_cookie(token: str | None) -> bool:
    expected = _admin_token()
    return bool(expected) and token == expected


async def _require_cookie(orion_admin: str | None = Cookie(None)) -> None:
    if not _check_cookie(orion_admin):
        raise HTTPException(
            status_code=303,
            detail="not authenticated",
            headers={"location": "/admin/ui/"},
        )


# ─── Login ────────────────────────────────────────────────────────────────


@router.get("/", response_class=HTMLResponse)
async def login_page(request: Request, orion_admin: str | None = Cookie(None)):
    if _check_cookie(orion_admin):
        return RedirectResponse(url="/admin/ui/users", status_code=303)
    return templates.TemplateResponse(request, "login.html", {})


@router.post("/login")
async def login(token: str = Form(...)):
    expected = _admin_token()
    if not expected:
        raise HTTPException(503, "ORION_MODEL_PROXY_ADMIN_KEY not configured")
    if token != expected:
        return RedirectResponse(url="/admin/ui/?err=invalid", status_code=303)
    resp = RedirectResponse(url="/admin/ui/users", status_code=303)
    resp.set_cookie(
        _COOKIE_NAME, token, httponly=True, samesite="strict",
        max_age=8 * 3600,  # 8h
    )
    return resp


@router.post("/logout")
async def logout():
    resp = RedirectResponse(url="/admin/ui/", status_code=303)
    resp.delete_cookie(_COOKIE_NAME)
    return resp


# ─── Users list ───────────────────────────────────────────────────────────


import datetime as dt


def _first_of_month_ts() -> int:
    now = dt.datetime.now(dt.timezone.utc).astimezone()
    first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return int(first.timestamp())


@router.get("/users", response_class=HTMLResponse)
async def users_page(
    request: Request,
    _=Depends(_require_cookie),
    s: AsyncSession = Depends(db_session),
):
    from sqlalchemy import func

    users = (await s.execute(select(User).order_by(User.created_at.desc()))).scalars().all()
    first = _first_of_month_ts()
    user_costs = []
    for u in users:
        stmt = (
            select(func.coalesce(func.sum(UsageLog.cost_usd), 0.0))
            .where(UsageLog.user_id == u.id)
            .where(UsageLog.ts >= first)
        )
        cost = float((await s.execute(stmt)).scalar() or 0.0)
        user_costs.append({
            "id": u.id, "email": u.email, "display_name": u.display_name,
            "budget_usd": u.budget_usd, "monthly_cost": cost,
        })
    return templates.TemplateResponse(request, "users.html", {"users": user_costs})


@router.post("/users")
async def create_user_action(
    email: str = Form(...),
    display_name: str = Form(""),
    budget_usd: str = Form(""),
    _=Depends(_require_cookie),
    s: AsyncSession = Depends(db_session),
):
    import secrets
    import time

    existing = (await s.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing is not None:
        return RedirectResponse(url="/admin/ui/users?err=duplicate", status_code=303)
    budget: float | None = None
    try:
        if budget_usd.strip():
            budget = float(budget_usd)
    except ValueError:
        pass
    user = User(
        id=secrets.token_hex(16),
        email=email,
        display_name=display_name or None,
        budget_usd=budget,
        created_at=int(time.time()),
    )
    s.add(user)
    await s.commit()
    return RedirectResponse(url=f"/admin/ui/users/{user.id}", status_code=303)


@router.post("/users/{user_id}/delete")
async def delete_user_action(
    user_id: str,
    _=Depends(_require_cookie),
    s: AsyncSession = Depends(db_session),
):
    user = await s.get(User, user_id)
    if user is not None:
        await s.delete(user)
        await s.commit()
        await invalidate_cache(None)
    return RedirectResponse(url="/admin/ui/users", status_code=303)


# ─── User detail ──────────────────────────────────────────────────────────


@router.get("/users/{user_id}", response_class=HTMLResponse)
async def user_detail_page(
    user_id: str,
    request: Request,
    new_token: str | None = None,
    _=Depends(_require_cookie),
    s: AsyncSession = Depends(db_session),
):
    user = await s.get(User, user_id)
    if user is None:
        return RedirectResponse(url="/admin/ui/users", status_code=303)
    keys = (
        await s.execute(
            select(ApiKey)
            .where(ApiKey.user_id == user_id)
            .order_by(ApiKey.created_at.desc())
        )
    ).scalars().all()

    # Usage rollup 當月 + by model
    from sqlalchemy import func

    first = _first_of_month_ts()
    rows = (
        await s.execute(
            select(UsageLog.model, func.sum(UsageLog.cost_usd), func.count(UsageLog.id))
            .where(UsageLog.user_id == user_id)
            .where(UsageLog.ts >= first)
            .group_by(UsageLog.model)
        )
    ).all()
    usage = [{"model": m, "cost": float(c), "count": int(n)} for m, c, n in rows]
    total_cost = sum(u["cost"] for u in usage)

    return templates.TemplateResponse(
        request,
        "user_detail.html",
        {
            "user": user,
            "keys": keys,
            "usage": usage,
            "total_cost": total_cost,
            "new_token": new_token,
        },
    )


@router.post("/users/{user_id}/keys")
async def gen_key_action(
    user_id: str,
    label: str = Form(""),
    env: str = Form("prod"),
    _=Depends(_require_cookie),
    s: AsyncSession = Depends(db_session),
):
    import secrets
    import time

    user = await s.get(User, user_id)
    if user is None:
        return RedirectResponse(url="/admin/ui/users", status_code=303)
    plaintext = generate_token(env=env)
    key = ApiKey(
        id=secrets.token_hex(16),
        user_id=user.id,
        token_hash=hash_token(plaintext),
        token_prefix=prefix_for_display(plaintext),
        label=label or None,
        created_at=int(time.time()),
    )
    s.add(key)
    await s.commit()
    return RedirectResponse(
        url=f"/admin/ui/users/{user_id}?new_token={plaintext}",
        status_code=303,
    )


@router.post("/keys/{key_id}/revoke")
async def revoke_key_action(
    key_id: str,
    _=Depends(_require_cookie),
    s: AsyncSession = Depends(db_session),
):
    import time

    from sqlalchemy import update

    key = await s.get(ApiKey, key_id)
    if key is None:
        return RedirectResponse(url="/admin/ui/users", status_code=303)
    await s.execute(
        update(ApiKey).where(ApiKey.id == key_id).values(revoked_at=int(time.time()))
    )
    await s.commit()
    await invalidate_cache(key.token_hash)
    return RedirectResponse(url=f"/admin/ui/users/{key.user_id}", status_code=303)


@router.post("/users/{user_id}/budget")
async def set_budget_action(
    user_id: str,
    budget_usd: str = Form(""),
    _=Depends(_require_cookie),
    s: AsyncSession = Depends(db_session),
):
    user = await s.get(User, user_id)
    if user is None:
        return RedirectResponse(url="/admin/ui/users", status_code=303)
    if not budget_usd.strip():
        user.budget_usd = None
    else:
        try:
            user.budget_usd = float(budget_usd)
        except ValueError:
            pass
    await s.commit()
    await invalidate_cache(None)
    return RedirectResponse(url=f"/admin/ui/users/{user_id}", status_code=303)


__all__ = ["router"]
