"""budget cap 達 → 402,沒設 cap → 一律放行。"""

from __future__ import annotations

import asyncio
import json
import os

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from orion_model_proxy.db import get_session_factory
from orion_model_proxy.models import UsageLog
from orion_model_proxy.server import create_app
from orion_model_proxy.usage_logger import (
    incr_running_cost,
    reset_running_cost_for_tests,
)


class _OkMockTransport(httpx.AsyncBaseTransport):
    def __init__(self, payload: bytes):
        self.payload = payload

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=self.payload,
            headers={"content-type": "application/json"},
        )


async def _create_user_with_key(
    app, admin_token: str, email: str, budget: float | None
) -> tuple[str, str]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {admin_token}"},
    ) as c:
        body: dict = {"email": email}
        if budget is not None:
            body["budget_usd"] = budget
        r = await c.post("/admin/users", json=body)
        uid = r.json()["id"]
        r = await c.post(f"/admin/users/{uid}/keys", json={"env": "test"})
        token = r.json()["token"]
    return uid, token


@pytest.mark.asyncio
async def test_no_budget_passes(proxy_db, admin_token, monkeypatch) -> None:
    """User 沒設 cap → 即使有 usage,proxy 也不擋。"""
    os.environ["OPENAI_API_KEY"] = "fake"
    payload = json.dumps({
        "model": "gpt-5-mini",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }).encode()
    transport = _OkMockTransport(payload)
    orig_init = httpx.AsyncClient.__init__

    def patched(self, *args, **kwargs):
        if "transport" not in kwargs:
            kwargs["transport"] = transport
        orig_init(self, *args, **kwargs)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)

    app = create_app()
    uid, token = await _create_user_with_key(app, admin_token, "nobud@x.com", None)

    # Pre-seed running_cost cache 一大筆,模擬「歷史累計很多」
    await incr_running_cost(uid, 1000.0)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as c:
        r = await c.post(
            "/openai/v1/chat/completions",
            json={"model": "gpt-5-mini", "messages": []},
        )
        assert r.status_code == 200
    os.environ.pop("OPENAI_API_KEY", None)


@pytest.mark.asyncio
async def test_budget_under_cap_passes(proxy_db, admin_token, monkeypatch) -> None:
    os.environ["OPENAI_API_KEY"] = "fake"
    payload = json.dumps({
        "model": "gpt-5-mini",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }).encode()
    transport = _OkMockTransport(payload)
    orig_init = httpx.AsyncClient.__init__

    def patched(self, *args, **kwargs):
        if "transport" not in kwargs:
            kwargs["transport"] = transport
        orig_init(self, *args, **kwargs)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)

    app = create_app()
    uid, token = await _create_user_with_key(app, admin_token, "under@x.com", 1.0)
    await incr_running_cost(uid, 0.5) # 用一半,還沒滿

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as c:
        r = await c.post(
            "/openai/v1/chat/completions",
            json={"model": "gpt-5-mini", "messages": []},
        )
        assert r.status_code == 200
    os.environ.pop("OPENAI_API_KEY", None)


@pytest.mark.asyncio
async def test_budget_over_cap_blocks_402(proxy_db, admin_token, monkeypatch) -> None:
    """User 累計 >= cap → 下次 request 直接 402,不打 upstream。"""
    os.environ["OPENAI_API_KEY"] = "fake"
    transport = _OkMockTransport(b"should-not-reach-upstream")
    orig_init = httpx.AsyncClient.__init__

    def patched(self, *args, **kwargs):
        if "transport" not in kwargs:
            kwargs["transport"] = transport
        orig_init(self, *args, **kwargs)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)

    app = create_app()
    uid, token = await _create_user_with_key(app, admin_token, "over@x.com", 1.0)
    await incr_running_cost(uid, 1.5) # 已超 cap

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as c:
        r = await c.post(
            "/openai/v1/chat/completions",
            json={"model": "gpt-5-mini", "messages": []},
        )
        assert r.status_code == 402
        assert "budget cap reached" in r.text
    os.environ.pop("OPENAI_API_KEY", None)


