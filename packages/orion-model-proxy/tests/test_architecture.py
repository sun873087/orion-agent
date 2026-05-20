"""Phase 33-E — routing alias / prompt cache / failover / organizations / WS。"""

from __future__ import annotations

import json
import time

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from orion_model_proxy.db import get_session_factory
from orion_model_proxy.models import PromptCache, RoutingAlias, User
from orion_model_proxy.server import create_app


# ─── Routing alias ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_routing_alias_user_first_then_global(proxy_db) -> None:
    from orion_model_proxy.routing import resolve_alias

    factory = get_session_factory()
    async with factory() as s:
        s.add(RoutingAlias(
            user_id=None, alias="auto",
            target_provider="anthropic", target_model="claude-haiku-4-5",
        ))
        s.add(RoutingAlias(
            user_id="u-custom", alias="auto",
            target_provider="openai", target_model="gpt-5-mini",
        ))
        await s.commit()

    factory = get_session_factory()
    async with factory() as s:
        # u-custom 有自己的 → 用 user 的
        r = await resolve_alias(s, alias="auto", user_id="u-custom")
        assert r == ("openai", "gpt-5-mini")
        # 另一 user → fallback global
        r = await resolve_alias(s, alias="auto", user_id="other")
        assert r == ("anthropic", "claude-haiku-4-5")
        # 未知 alias → None
        r = await resolve_alias(s, alias="nope", user_id="other")
        assert r is None


def test_rewrite_model_in_body() -> None:
    from orion_model_proxy.routing import rewrite_model_in_body

    body = json.dumps({"model": "auto", "messages": [{"role": "user", "content": "hi"}]}).encode()
    out = rewrite_model_in_body(body, "gpt-5-mini")
    assert json.loads(out)["model"] == "gpt-5-mini"

    # 沒 model 欄 — 原樣回
    body = json.dumps({"input": "hi"}).encode()
    out = rewrite_model_in_body(body, "gpt-5-mini")
    assert out == body

    # 非 JSON — 原樣
    body = b"not json"
    assert rewrite_model_in_body(body, "x") == body


@pytest.mark.asyncio
async def test_admin_routing_alias_crud(proxy_db, admin_token) -> None:
    app = create_app()
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t", headers=headers) as c:
        r = await c.post("/admin/routing_aliases", json={
            "alias": "fast",
            "target_provider": "openai",
            "target_model": "gpt-5-mini",
        })
        assert r.status_code == 201

        r = await c.get("/admin/routing_aliases")
        assert any(a["alias"] == "fast" for a in r.json())


# ─── Prompt cache ─────────────────────────────────────────────────────────


def test_prompt_cache_hash_skips_stream_and_tools() -> None:
    from orion_model_proxy.cache import compute_content_hash

    # 正常 chat
    body = json.dumps({"messages": [{"role": "user", "content": "hi"}], "temperature": 0}).encode()
    h = compute_content_hash("gpt-5-mini", body)
    assert h is not None
    assert len(h) == 64

    # Stream
    body = json.dumps({"stream": True, "messages": []}).encode()
    assert compute_content_hash("gpt-5", body) is None

    # 帶 tools
    body = json.dumps({"messages": [], "tools": []}).encode()
    assert compute_content_hash("gpt-5", body) is None


def test_prompt_cache_hash_deterministic() -> None:
    from orion_model_proxy.cache import compute_content_hash

    body1 = json.dumps({"messages": [{"role": "user", "content": "hi"}], "temperature": 0}).encode()
    body2 = json.dumps({"temperature": 0, "messages": [{"role": "user", "content": "hi"}]}).encode()
    # Order-different JSON → 相同 hash(因為 sort_keys)
    assert compute_content_hash("m", body1) == compute_content_hash("m", body2)
    # Model 不同 → hash 不同
    assert compute_content_hash("a", body1) != compute_content_hash("b", body1)


@pytest.mark.asyncio
async def test_prompt_cache_store_and_lookup(proxy_db) -> None:
    from orion_model_proxy.cache import compute_content_hash, lookup, store

    body = json.dumps({"messages": [{"role": "user", "content": "test"}]}).encode()
    h = compute_content_hash("gpt-5", body)
    assert h

    factory = get_session_factory()
    # Miss
    async with factory() as s:
        assert await lookup(s, h) is None

    # Store
    async with factory() as s:
        await store(s, content_hash=h, provider="openai", model="gpt-5",
                    response_blob=b'{"choices":[{"message":{"content":"cached"}}]}')

    # Hit + hit_count incr
    async with factory() as s:
        blob = await lookup(s, h)
        assert blob is not None
        assert b"cached" in blob

    async with factory() as s:
        row = (await s.execute(select(PromptCache).where(PromptCache.content_hash == h))).scalar_one()
        assert row.hit_count == 1


# ─── Failover ─────────────────────────────────────────────────────────────


def test_failover_chain_known_models() -> None:
    from orion_model_proxy.failover import get_fallback_chain

    chain = get_fallback_chain("openai", "gpt-5")
    assert len(chain) > 0
    assert chain[0].provider == "anthropic"


def test_failover_should_failover_status() -> None:
    from orion_model_proxy.failover import should_failover

    assert should_failover(429) is True
    assert should_failover(500) is True
    assert should_failover(503) is True
    assert should_failover(401) is False
    assert should_failover(403) is False
    assert should_failover(200) is False


# ─── Organizations ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_organizations_crud(proxy_db, admin_token) -> None:
    app = create_app()
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t", headers=headers) as c:
        r = await c.post("/admin/organizations", json={
            "name": "Acme Corp", "monthly_budget_usd": 500.0,
        })
        assert r.status_code == 201
        oid = r.json()["id"]
        assert r.json()["monthly_budget_usd"] == 500.0

        r = await c.get("/admin/organizations")
        assert any(o["id"] == oid for o in r.json())


# ─── WebSocket stub ───────────────────────────────────────────────────────


def test_realtime_websocket_returns_not_implemented(proxy_db, admin_token) -> None:
    """OpenAI Realtime WS endpoint registered but 503 — Phase E skeleton。"""
    from fastapi.testclient import TestClient

    app = create_app()
    client = TestClient(app)
    with client.websocket_connect("/openai/v1/realtime") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert msg["error"]["code"] == "NOT_IMPLEMENTED"
