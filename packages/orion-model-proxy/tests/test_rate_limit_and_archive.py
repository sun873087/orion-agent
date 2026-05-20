"""token bucket rate limit + usage_log monthly archival。"""

from __future__ import annotations

import asyncio
import time

import pytest
from sqlalchemy import select

from orion_model_proxy.db import get_session_factory
from orion_model_proxy.models import UsageLog, UsageMonthlyRollup


# ─── Rate limit ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rate_limit_under_quota_passes(proxy_db) -> None:
    from orion_model_proxy.rate_limit import check_and_consume, reset_for_tests

    await reset_for_tests()
    # 60 RPM = 1 per second steady-state,但初始 burst 滿 60
    for _ in range(50):
        assert await check_and_consume("u1", 60) is True


@pytest.mark.asyncio
async def test_rate_limit_burst_then_block(proxy_db) -> None:
    from orion_model_proxy.rate_limit import check_and_consume, reset_for_tests

    await reset_for_tests()
    # 用 burst 全部
    rpm = 10
    for _ in range(rpm):
        assert await check_and_consume("burst", rpm) is True
    # 11th 立刻丟 → 沒 refill time
    assert await check_and_consume("burst", rpm) is False


@pytest.mark.asyncio
async def test_rate_limit_refill_over_time(proxy_db) -> None:
    from orion_model_proxy import rate_limit
    from orion_model_proxy.rate_limit import check_and_consume, reset_for_tests

    await reset_for_tests()
    rpm = 60
    # 燒完
    for _ in range(rpm):
        await check_and_consume("refill", rpm)
    assert await check_and_consume("refill", rpm) is False
    # 模擬時間流逝:直接修 bucket last_refill_ts
    async with rate_limit._lock:
        rate_limit._buckets["refill"].last_refill_ts -= 2.0 # 2 秒前
    # 60 RPM × 2s = 2 tokens 可用
    assert await check_and_consume("refill", rpm) is True
    assert await check_and_consume("refill", rpm) is True
    assert await check_and_consume("refill", rpm) is False # 用完


@pytest.mark.asyncio
async def test_rate_limit_zero_means_unlimited(proxy_db) -> None:
    from orion_model_proxy.rate_limit import check_and_consume, reset_for_tests

    await reset_for_tests()
    for _ in range(10000):
        assert await check_and_consume("u", 0) is True


@pytest.mark.asyncio
async def test_admin_set_rate_limit(proxy_db, admin_token) -> None:
    from httpx import ASGITransport, AsyncClient
    from orion_model_proxy.server import create_app

    app = create_app()
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t", headers=headers) as c:
        r = await c.post("/admin/users", json={"email": "rl@x.com"})
        uid = r.json()["id"]
        r = await c.post(f"/admin/users/{uid}/rate_limit", json={"rate_limit_rpm": 30})
        assert r.status_code == 200
        # GET user 看不到 rate_limit_rpm(UserOut 沒 expose)— audit 一定要 record
        from orion_model_proxy.models import AuditLog
        factory = get_session_factory()
        async with factory() as s:
            actions = [
                e.action for e in
                (await s.execute(select(AuditLog).where(AuditLog.action == "rate_limit.set"))).scalars().all()
            ]
        assert "rate_limit.set" in actions


# ─── Usage archival ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_archive_old_rows_into_monthly_rollup(proxy_db) -> None:
    """120 天前的 row 應被 archive,30 天內的 row 不動。"""
    from orion_model_proxy.archive import archive_usage_log

    factory = get_session_factory()
    now = int(time.time())
    old_ts = now - 120 * 86400
    recent_ts = now - 15 * 86400

    async with factory() as s:
        # 5 個舊 row 同一 user / model
        for _ in range(5):
            s.add(UsageLog(
                user_id="u-a", api_key_id="k1",
                provider="openai", model="gpt-5-mini",
                endpoint="/openai/v1/chat/completions",
                input_tokens=100, output_tokens=50,
                cache_read_tokens=0, cache_creation_tokens=None,
                cost_usd=0.001, ts=old_ts, client_id=None, request_id=None,
            ))
        # 2 個新 row
        for _ in range(2):
            s.add(UsageLog(
                user_id="u-a", api_key_id="k1",
                provider="openai", model="gpt-5-mini",
                endpoint="/openai/v1/chat/completions",
                input_tokens=10, output_tokens=5,
                cache_read_tokens=0, cache_creation_tokens=None,
                cost_usd=0.0001, ts=recent_ts, client_id=None, request_id=None,
            ))
        await s.commit()

    async with factory() as s:
        stats = await archive_usage_log(s, cutoff_days=90)

    assert stats.rows_archived == 5
    assert stats.rollup_rows_upserted == 1 # 5 row 聚合成 1

    async with factory() as s:
        # 舊 row 沒了
        remaining = (await s.execute(select(UsageLog).where(UsageLog.user_id == "u-a"))).scalars().all()
        assert len(remaining) == 2
        # Rollup 有 1 row,sums 對
        rollups = (await s.execute(select(UsageMonthlyRollup))).scalars().all()
    assert len(rollups) == 1
    r = rollups[0]
    assert r.user_id == "u-a"
    assert r.total_input_tokens == 500 # 5 × 100
    assert r.total_output_tokens == 250 # 5 × 50
    assert r.request_count == 5
    assert abs(r.total_cost_usd - 0.005) < 1e-9


@pytest.mark.asyncio
async def test_archive_idempotent_second_call_noop(proxy_db) -> None:
    from orion_model_proxy.archive import archive_usage_log

    factory = get_session_factory()
    async with factory() as s:
        stats = await archive_usage_log(s, cutoff_days=90)
    assert stats.rows_archived == 0

    # 第二次跑 — 沒新 row 仍 0
    async with factory() as s:
        stats = await archive_usage_log(s, cutoff_days=90)
    assert stats.rows_archived == 0


@pytest.mark.asyncio
async def test_archive_admin_endpoint(proxy_db, admin_token) -> None:
    from httpx import ASGITransport, AsyncClient
    from orion_model_proxy.server import create_app

    app = create_app()
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t", headers=headers) as c:
        r = await c.post("/admin/maintenance/archive?cutoff_days=90")
        assert r.status_code == 200
        data = r.json()
        assert data["rows_archived"] == 0 # 空 DB
