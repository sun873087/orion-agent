"""Admin REST + Web UI routes。

REST:
    POST /admin/users
    GET /admin/users
    DELETE /admin/users/{user_id}
    POST /admin/users/{user_id}/keys gen new(回明文一次)
    DELETE /admin/keys/{key_id} revoke
    POST /admin/users/{user_id}/budget set cap
    GET /admin/users/{user_id}/usage rollup

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

from orion_model_proxy.audit import record as audit_record
from orion_model_proxy.auth import (
    generate_token,
    hash_token,
    invalidate_cache,
    prefix_for_display,
    require_admin,
)
from orion_model_proxy.db import session as db_session
from orion_model_proxy.models import (
    ApiKey, AuditLog, Organization, RoutingAlias, UsageLog, User, Webhook,
)


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
    budget_usd: float | None # None = 取消 cap


class SetRateLimitRequest(BaseModel):
    rate_limit_rpm: int | None # None or 0 = unlimited


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
    await audit_record(
        s, action="user.create", target_type="user", target_id=user.id,
        detail={"email": req.email, "budget_usd": req.budget_usd},
    )
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
    email = user.email
    await s.delete(user)
    await s.commit()
    await invalidate_cache(None) # flush cache,可能 user 的 key 還在
    await audit_record(
        s, action="user.delete", target_type="user", target_id=user_id,
        detail={"email": email},
    )


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
        token=plaintext, # 唯一一次回明文
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
        return # 已 revoked,idempotent
    await s.execute(
        update(ApiKey).where(ApiKey.id == key_id).values(revoked_at=_now())
    )
    await s.commit()
    await invalidate_cache(key.token_hash)
    await audit_record(
        s, action="key.revoke", target_type="key", target_id=key_id,
        detail={"user_id": key.user_id, "prefix": key.token_prefix},
    )


@router.post("/keys/{key_id}/rotate", response_model=CreateKeyResponse, status_code=201)
async def rotate_key(
    key_id: str, s: AsyncSession = Depends(db_session)
) -> CreateKeyResponse:
    """Atomic rotate:gen 一個跟舊 key 同 user/label 的新 key + 把舊的 revoke。
    回明文新 token(只一次)。Admin UI 一鍵流程,不必兩步操作。"""
    old = await s.get(ApiKey, key_id)
    if old is None:
        raise HTTPException(status_code=404, detail=f"key {key_id} not found")
    if old.revoked_at is not None:
        raise HTTPException(status_code=400, detail=f"key {key_id} already revoked")
    # 從原 prefix 抽 env 段(sk-orion-<env>-...)
    parts = old.token_prefix.split("-", 3)
    env = parts[2] if len(parts) >= 3 else "prod"
    plaintext = generate_token(env=env)
    new_key = ApiKey(
        id=_new_id(),
        user_id=old.user_id,
        token_hash=hash_token(plaintext),
        token_prefix=prefix_for_display(plaintext),
        label=old.label,
        created_at=_now(),
    )
    s.add(new_key)
    # revoke 舊的(同 transaction)
    await s.execute(
        update(ApiKey).where(ApiKey.id == key_id).values(revoked_at=_now())
    )
    await s.commit()
    await s.refresh(new_key)
    await invalidate_cache(old.token_hash)
    await audit_record(
        s, action="key.rotate", target_type="key", target_id=new_key.id,
        detail={
            "user_id": old.user_id,
            "old_key_id": key_id,
            "old_prefix": old.token_prefix,
            "new_prefix": new_key.token_prefix,
        },
    )
    return CreateKeyResponse(
        id=new_key.id,
        user_id=new_key.user_id,
        label=new_key.label,
        token=plaintext,
        token_prefix=new_key.token_prefix,
        created_at=new_key.created_at,
    )


# ─── Budget ──────────────────────────────────────────────────────────────


@router.post("/users/{user_id}/rate_limit", response_model=UserOut)
async def set_rate_limit(
    user_id: str,
    req: SetRateLimitRequest,
    s: AsyncSession = Depends(db_session),
) -> UserOut:
    user = await s.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"user {user_id} not found")
    old = user.rate_limit_rpm
    user.rate_limit_rpm = req.rate_limit_rpm
    await s.commit()
    await s.refresh(user)
    await invalidate_cache(None) # principal cache 帶 rpm,要 refresh
    await audit_record(
        s, action="rate_limit.set", target_type="user", target_id=user_id,
        detail={"old": old, "new": req.rate_limit_rpm},
    )
    return await _user_to_out(s, user)


@router.post("/users/{user_id}/budget", response_model=UserOut)
async def set_budget(
    user_id: str,
    req: SetBudgetRequest,
    s: AsyncSession = Depends(db_session),
) -> UserOut:
    user = await s.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"user {user_id} not found")
    old = user.budget_usd
    user.budget_usd = req.budget_usd
    await s.commit()
    await s.refresh(user)
    await invalidate_cache(None) # principal cache 帶 budget,得 refresh
    await audit_record(
        s, action="budget.set", target_type="user", target_id=user_id,
        detail={"old": old, "new": req.budget_usd},
    )
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


class AuditEntry(BaseModel):
    id: int
    ts: int
    action: str
    target_type: str | None
    target_id: str | None
    detail: str | None


@router.get("/audit", response_model=list[AuditEntry])
async def list_audit(
    limit: int = 100, s: AsyncSession = Depends(db_session)
) -> list[AuditEntry]:
    """最近 N 筆 admin action audit log。"""
    limit = max(1, min(limit, 1000))
    rows = (
        await s.execute(select(AuditLog).order_by(AuditLog.ts.desc()).limit(limit))
    ).scalars().all()
    return [
        AuditEntry(
            id=r.id, ts=r.ts, action=r.action,
            target_type=r.target_type, target_id=r.target_id, detail=r.detail,
        )
        for r in rows
    ]


class DailyPoint(BaseModel):
    date: str # "YYYY-MM-DD"
    cost_usd: float
    request_count: int


@router.get("/users/{user_id}/usage/daily", response_model=list[DailyPoint])
async def get_usage_daily(
    user_id: str,
    days: int = 30,
    s: AsyncSession = Depends(db_session),
) -> list[DailyPoint]:
    """過去 N 天 daily aggregate — 給 admin UI 畫 sparkline / chart。

    SQLite 跟 Postgres date 函式不同 — 用 epoch / 86400 整數 bucket 做 group by。
    """
    import datetime as dt

    days = max(1, min(days, 365))
    now = dt.datetime.now(dt.timezone.utc)
    end_ts = int(now.timestamp())
    start_ts = end_ts - days * 86400

    # 拉 row 後 Python 端 bucket(避免 SQLite/PG date 函式分歧)
    rows = (
        await s.execute(
            select(UsageLog.ts, UsageLog.cost_usd)
            .where(UsageLog.user_id == user_id)
            .where(UsageLog.ts >= start_ts)
            .where(UsageLog.ts <= end_ts)
        )
    ).all()
    buckets: dict[str, tuple[float, int]] = {}
    for ts, cost in rows:
        d = dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d")
        prev_cost, prev_n = buckets.get(d, (0.0, 0))
        buckets[d] = (prev_cost + float(cost), prev_n + 1)
    # 補空缺天為 0
    out: list[DailyPoint] = []
    for i in range(days, -1, -1):
        d = (now - dt.timedelta(days=i)).strftime("%Y-%m-%d")
        cost, n = buckets.get(d, (0.0, 0))
        out.append(DailyPoint(date=d, cost_usd=round(cost, 6), request_count=n))
    return out


class OrgCreateRequest(BaseModel):
    name: str
    monthly_budget_usd: float | None = None


class OrgOut(BaseModel):
    id: str
    name: str
    monthly_budget_usd: float | None
    created_at: int


@router.post("/organizations", response_model=OrgOut, status_code=201)
async def create_org(
    req: OrgCreateRequest, s: AsyncSession = Depends(db_session)
) -> OrgOut:
    org = Organization(
        id=_new_id(),
        name=req.name,
        monthly_budget_usd=req.monthly_budget_usd,
        created_at=_now(),
    )
    s.add(org)
    await s.commit()
    await audit_record(
        s, action="org.create", target_type="org", target_id=org.id,
        detail={"name": req.name},
    )
    return OrgOut(
        id=org.id, name=org.name,
        monthly_budget_usd=org.monthly_budget_usd, created_at=org.created_at,
    )


@router.get("/organizations", response_model=list[OrgOut])
async def list_orgs(s: AsyncSession = Depends(db_session)) -> list[OrgOut]:
    rows = (await s.execute(select(Organization))).scalars().all()
    return [
        OrgOut(
            id=o.id, name=o.name,
            monthly_budget_usd=o.monthly_budget_usd, created_at=o.created_at,
        )
        for o in rows
    ]


class RoutingAliasCreateRequest(BaseModel):
    user_id: str | None = None # None = global
    alias: str
    target_provider: str
    target_model: str


class RoutingAliasOut(BaseModel):
    id: int
    user_id: str | None
    alias: str
    target_provider: str
    target_model: str


@router.post("/routing_aliases", response_model=RoutingAliasOut, status_code=201)
async def create_routing_alias(
    req: RoutingAliasCreateRequest, s: AsyncSession = Depends(db_session)
) -> RoutingAliasOut:
    row = RoutingAlias(
        user_id=req.user_id,
        alias=req.alias,
        target_provider=req.target_provider,
        target_model=req.target_model,
    )
    s.add(row)
    await s.commit()
    await s.refresh(row)
    await audit_record(
        s, action="routing.create", target_type="routing", target_id=str(row.id),
        detail={"alias": req.alias, "target": f"{req.target_provider}/{req.target_model}"},
    )
    return RoutingAliasOut(
        id=row.id, user_id=row.user_id, alias=row.alias,
        target_provider=row.target_provider, target_model=row.target_model,
    )


@router.get("/routing_aliases", response_model=list[RoutingAliasOut])
async def list_routing_aliases(s: AsyncSession = Depends(db_session)) -> list[RoutingAliasOut]:
    rows = (await s.execute(select(RoutingAlias))).scalars().all()
    return [
        RoutingAliasOut(
            id=r.id, user_id=r.user_id, alias=r.alias,
            target_provider=r.target_provider, target_model=r.target_model,
        )
        for r in rows
    ]


class WebhookCreateRequest(BaseModel):
    user_id: str | None = None # None = global
    event: str # e.g. "budget.exceeded"
    url: str


class WebhookOut(BaseModel):
    id: str
    user_id: str | None
    event: str
    url: str
    enabled: bool
    created_at: int


@router.post("/webhooks", response_model=WebhookOut, status_code=201)
async def create_webhook(
    req: WebhookCreateRequest, s: AsyncSession = Depends(db_session)
) -> WebhookOut:
    w = Webhook(
        id=_new_id(),
        user_id=req.user_id,
        event=req.event,
        url=req.url,
        enabled=True,
        created_at=_now(),
    )
    s.add(w)
    await s.commit()
    await audit_record(
        s, action="webhook.create", target_type="webhook", target_id=w.id,
        detail={"event": req.event, "user_id": req.user_id},
    )
    return WebhookOut(
        id=w.id, user_id=w.user_id, event=w.event, url=w.url,
        enabled=w.enabled, created_at=w.created_at,
    )


@router.get("/webhooks", response_model=list[WebhookOut])
async def list_webhooks(s: AsyncSession = Depends(db_session)) -> list[WebhookOut]:
    rows = (await s.execute(select(Webhook))).scalars().all()
    return [
        WebhookOut(
            id=w.id, user_id=w.user_id, event=w.event, url=w.url,
            enabled=w.enabled, created_at=w.created_at,
        )
        for w in rows
    ]


@router.delete("/webhooks/{webhook_id}", status_code=204)
async def delete_webhook(webhook_id: str, s: AsyncSession = Depends(db_session)) -> None:
    w = await s.get(Webhook, webhook_id)
    if w is None:
        raise HTTPException(404, f"webhook {webhook_id} not found")
    await s.delete(w)
    await s.commit()
    await audit_record(
        s, action="webhook.delete", target_type="webhook", target_id=webhook_id,
    )


class BackupOut(BaseModel):
    path: str
    schema_version: int
    exported_at: int
    table_counts: dict[str, int]


@router.post("/maintenance/backup", response_model=BackupOut)
async def backup_proxy_db(
    target_path: str, s: AsyncSession = Depends(db_session)
) -> BackupOut:
    """Dump 全 proxy DB(users / api_keys / usage_log / audit / ...)到 zip。
    target_path 由 admin 提供絕對路徑。"""
    from pathlib import Path
    from orion_model_proxy.backup import backup_to_zip

    p = Path(target_path).expanduser()
    if not target_path.endswith(".zip"):
        raise HTTPException(400, "target_path 必須以 .zip 結尾")
    stats = await backup_to_zip(s, p)
    await audit_record(
        s, action="maintenance.backup", target_type=None,
        detail={"path": str(p), "table_counts": stats.table_counts},
    )
    return BackupOut(
        path=stats.path,
        schema_version=stats.schema_version,
        exported_at=stats.exported_at,
        table_counts=stats.table_counts,
    )


class RestoreOut(BaseModel):
    schema_version: int
    table_counts: dict[str, int]


@router.post("/maintenance/restore", response_model=RestoreOut)
async def restore_proxy_db(
    source_path: str,
    replace_all: bool = True,
    s: AsyncSession = Depends(db_session),
) -> RestoreOut:
    """從 zip 還原(預設 replace_all,truncate 全表 + insert)。"""
    from pathlib import Path
    from orion_model_proxy.backup import restore_from_zip

    p = Path(source_path).expanduser()
    if not p.is_file():
        raise HTTPException(404, f"{p} not found")
    try:
        stats = await restore_from_zip(s, p, replace_all=replace_all)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    # invalidate auth cache(token DB 全換了)
    from orion_model_proxy.auth import invalidate_cache
    await invalidate_cache(None)
    return RestoreOut(
        schema_version=stats.schema_version,
        table_counts=stats.table_counts,
    )


class ArchiveResult(BaseModel):
    rows_archived: int
    rollup_rows_upserted: int
    cutoff_ts: int


@router.post("/maintenance/archive", response_model=ArchiveResult)
async def archive_usage(
    cutoff_days: int = 90, s: AsyncSession = Depends(db_session)
) -> ArchiveResult:
    """把 cutoff_days 前的 usage_log row 壓進 usage_monthly。

    Admin 手動觸發(也可 cron / scheduler 跑)。Idempotent — 多呼一次只是
    把更舊資料再聚合(若有的話)。
    """
    cutoff_days = max(1, min(cutoff_days, 3650))
    from orion_model_proxy.archive import archive_usage_log
    stats = await archive_usage_log(s, cutoff_days=cutoff_days)
    await audit_record(
        s, action="maintenance.archive", target_type=None,
        detail={
            "rows_archived": stats.rows_archived,
            "rollup_upserted": stats.rollup_rows_upserted,
            "cutoff_days": cutoff_days,
        },
    )
    return ArchiveResult(
        rows_archived=stats.rows_archived,
        rollup_rows_upserted=stats.rollup_rows_upserted,
        cutoff_ts=stats.cutoff_ts,
    )


__all__ = ["router"]
