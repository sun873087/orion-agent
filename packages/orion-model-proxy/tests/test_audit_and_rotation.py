"""Phase 33-A — audit log + token rotation + sparkline timeseries。"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from orion_model_proxy.db import get_session_factory
from orion_model_proxy.models import ApiKey, AuditLog
from orion_model_proxy.server import create_app


def _admin_client(admin_token: str) -> AsyncClient:
    app = create_app()
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {admin_token}"},
    )


@pytest.mark.asyncio
async def test_user_create_records_audit(proxy_db, admin_token) -> None:
    async with _admin_client(admin_token) as c:
        r = await c.post("/admin/users", json={"email": "audit@x.com", "budget_usd": 5.0})
        uid = r.json()["id"]

    factory = get_session_factory()
    async with factory() as s:
        entries = (await s.execute(select(AuditLog).order_by(AuditLog.ts))).scalars().all()
    actions = [e.action for e in entries]
    assert "user.create" in actions
    create_entry = next(e for e in entries if e.action == "user.create")
    assert create_entry.target_id == uid


@pytest.mark.asyncio
async def test_key_lifecycle_records_audit(proxy_db, admin_token) -> None:
    """create user → gen key → revoke → audit log 有 3 筆。"""
    async with _admin_client(admin_token) as c:
        r = await c.post("/admin/users", json={"email": "klife@x.com"})
        uid = r.json()["id"]
        r = await c.post(f"/admin/users/{uid}/keys", json={"env": "test"})
        kid = r.json()["id"]
        await c.delete(f"/admin/keys/{kid}")

    factory = get_session_factory()
    async with factory() as s:
        actions = [
            e.action for e in
            (await s.execute(select(AuditLog).order_by(AuditLog.ts))).scalars().all()
        ]
    assert "user.create" in actions
    assert "key.revoke" in actions


@pytest.mark.asyncio
async def test_token_rotation_atomic(proxy_db, admin_token) -> None:
    """rotate → 舊 key revoked + 新 key active + audit 有 key.rotate + 兩個 key
    都掛同一 user_id + 同 label。"""
    async with _admin_client(admin_token) as c:
        r = await c.post("/admin/users", json={"email": "rot@x.com"})
        uid = r.json()["id"]
        r = await c.post(
            f"/admin/users/{uid}/keys",
            json={"label": "laptop", "env": "prod"},
        )
        old_kid = r.json()["id"]
        old_token = r.json()["token"]

        r = await c.post(f"/admin/keys/{old_kid}/rotate")
        assert r.status_code == 201, r.text
        new_data = r.json()
        new_token = new_data["token"]
        assert new_token != old_token
        assert new_data["label"] == "laptop"
        assert new_data["token_prefix"].startswith("sk-orion-prod-")

        # 列 keys:舊 revoked、新 active
        r = await c.get(f"/admin/users/{uid}/keys")
        keys = r.json()
        old = next(k for k in keys if k["id"] == old_kid)
        new = next(k for k in keys if k["id"] == new_data["id"])
        assert old["revoked_at"] is not None
        assert new["revoked_at"] is None
        assert old["label"] == new["label"] == "laptop"

    # Audit log 有 key.rotate
    factory = get_session_factory()
    async with factory() as s:
        actions = [
            e.action for e in
            (await s.execute(select(AuditLog).order_by(AuditLog.ts))).scalars().all()
        ]
    assert "key.rotate" in actions


@pytest.mark.asyncio
async def test_rotation_blocks_double_rotate(proxy_db, admin_token) -> None:
    """已 revoked 的 key 不能再 rotate(避免 race condition)。"""
    async with _admin_client(admin_token) as c:
        r = await c.post("/admin/users", json={"email": "rot2@x.com"})
        uid = r.json()["id"]
        r = await c.post(f"/admin/users/{uid}/keys", json={"env": "prod"})
        kid = r.json()["id"]
        await c.delete(f"/admin/keys/{kid}")

        r = await c.post(f"/admin/keys/{kid}/rotate")
        assert r.status_code == 400
        assert "already revoked" in r.text


@pytest.mark.asyncio
async def test_audit_list_endpoint(proxy_db, admin_token) -> None:
    async with _admin_client(admin_token) as c:
        await c.post("/admin/users", json={"email": "a@x.com"})
        await c.post("/admin/users", json={"email": "b@x.com"})

        r = await c.get("/admin/audit?limit=10")
        assert r.status_code == 200
        entries = r.json()
        assert len(entries) >= 2
        assert all("ts" in e and "action" in e for e in entries)


@pytest.mark.asyncio
async def test_usage_daily_returns_padded_zeros(proxy_db, admin_token) -> None:
    """沒任何 usage → daily timeseries 全 0,但天數正確。"""
    async with _admin_client(admin_token) as c:
        r = await c.post("/admin/users", json={"email": "spark@x.com"})
        uid = r.json()["id"]

        r = await c.get(f"/admin/users/{uid}/usage/daily?days=7")
        assert r.status_code == 200
        pts = r.json()
        assert len(pts) == 8  # 7 天 + today
        assert all(p["cost_usd"] == 0.0 and p["request_count"] == 0 for p in pts)


@pytest.mark.asyncio
async def test_budget_set_records_audit(proxy_db, admin_token) -> None:
    async with _admin_client(admin_token) as c:
        r = await c.post("/admin/users", json={"email": "bud@x.com"})
        uid = r.json()["id"]
        await c.post(f"/admin/users/{uid}/budget", json={"budget_usd": 10.0})
        await c.post(f"/admin/users/{uid}/budget", json={"budget_usd": 50.0})

    factory = get_session_factory()
    async with factory() as s:
        budgets = [
            e for e in
            (await s.execute(select(AuditLog).where(AuditLog.action == "budget.set"))).scalars().all()
        ]
    assert len(budgets) == 2
