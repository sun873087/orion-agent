"""webhook emit + OTel skeleton no-op。"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from orion_model_proxy.db import get_session_factory
from orion_model_proxy.models import User, Webhook
from orion_model_proxy.server import create_app


@pytest.mark.asyncio
async def test_webhook_crud(proxy_db, admin_token) -> None:
    app = create_app()
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t", headers=headers) as c:
        r = await c.post(
            "/admin/webhooks",
            json={"event": "budget.exceeded", "url": "http://example.com/hook"},
        )
        assert r.status_code == 201
        wid = r.json()["id"]
        assert r.json()["enabled"] is True

        r = await c.get("/admin/webhooks")
        assert any(w["id"] == wid for w in r.json())

        r = await c.delete(f"/admin/webhooks/{wid}")
        assert r.status_code == 204

        r = await c.get("/admin/webhooks")
        assert all(w["id"] != wid for w in r.json())


@pytest.mark.asyncio
async def test_budget_webhook_fires_once_per_event(proxy_db) -> None:
    """同 user 同 event 只 fire 一次,直到 reset。"""
    from orion_model_proxy import webhook as wh_mod
    from orion_model_proxy.webhook import maybe_emit_budget_event

    await wh_mod.reset_for_tests()

    factory = get_session_factory()
    now = int(time.time())
    async with factory() as s:
        s.add(User(id="wu", email="wu@x.com", display_name=None,
                   budget_usd=10.0, created_at=now))
        s.add(Webhook(
            id="w1", user_id="wu", event="budget.warning_80",
            url="http://hook.local", enabled=True, created_at=now,
        ))
        s.add(Webhook(
            id="w2", user_id="wu", event="budget.exceeded",
            url="http://hook.local", enabled=True, created_at=now,
        ))
        await s.commit()

    posts: list[tuple[str, dict]] = []

    async def fake_post(url: str, payload: dict) -> None:
        posts.append((url, payload))

    with patch.object(wh_mod, "_post_one", fake_post):
        async with factory() as s:
            # 用 8 = 80%,觸發 warning
            await maybe_emit_budget_event(s, user_id="wu", running_cost=8.0, budget_cap=10.0)
            # 再呼一次 — 不該再 fire warning
            await maybe_emit_budget_event(s, user_id="wu", running_cost=8.5, budget_cap=10.0)
            # 12 = 120%,觸發 exceeded
            await maybe_emit_budget_event(s, user_id="wu", running_cost=12.0, budget_cap=10.0)
            # 再呼 — 不該再 fire exceeded
            await maybe_emit_budget_event(s, user_id="wu", running_cost=15.0, budget_cap=10.0)

    # 給背景 task 一點時間
    for _ in range(20):
        if len(posts) >= 2:
            break
        await asyncio.sleep(0.02)

    events = [p["event"] for _, p in posts]
    assert events.count("budget.warning_80") == 1
    assert events.count("budget.exceeded") == 1


@pytest.mark.asyncio
async def test_global_webhook_fires_for_all_users(proxy_db) -> None:
    """user_id NULL 的 webhook → 任何 user 的 event 都觸發。"""
    from orion_model_proxy import webhook as wh_mod
    from orion_model_proxy.webhook import maybe_emit_budget_event

    await wh_mod.reset_for_tests()

    factory = get_session_factory()
    now = int(time.time())
    async with factory() as s:
        s.add(User(id="g1", email="g1@x.com", display_name=None,
                   budget_usd=10.0, created_at=now))
        s.add(Webhook(
            id="ghook", user_id=None, event="budget.exceeded",
            url="http://global.hook", enabled=True, created_at=now,
        ))
        await s.commit()

    posts: list[tuple[str, dict]] = []

    async def fake_post(url: str, payload: dict) -> None:
        posts.append((url, payload))

    with patch.object(wh_mod, "_post_one", fake_post):
        async with factory() as s:
            await maybe_emit_budget_event(s, user_id="g1", running_cost=15.0, budget_cap=10.0)

    for _ in range(20):
        if posts:
            break
        await asyncio.sleep(0.02)

    assert any(url == "http://global.hook" for url, _ in posts)


def test_otel_span_noop_when_env_unset() -> None:
    """OTEL_EXPORTER_OTLP_ENDPOINT 沒設 → span context manager 不 crash。"""
    import os
    from orion_model_proxy.telemetry import span

    os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
    with span("test", user_id="u", action="x"):
        pass # 沒 raise 就 OK
