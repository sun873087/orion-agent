"""Phase X.2 integration — mock upstream OpenAI/Anthropic,verify tee
parses usage + 寫進 DB。"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from orion_model_proxy.db import get_session_factory
from orion_model_proxy.models import UsageLog
from orion_model_proxy.server import create_app


class _MockUpstreamTransport(httpx.AsyncBaseTransport):
    """攔下 httpx.AsyncClient.send,看 URL host 判斷 upstream 回什麼。"""

    def __init__(self, openai_payload: bytes, openai_ct: str = "application/json"):
        self.openai_payload = openai_payload
        self.openai_ct = openai_ct
        self.last_request: httpx.Request | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.last_request = request
        host = request.url.host
        if "openai" in host:
            return httpx.Response(
                200, content=self.openai_payload,
                headers={"content-type": self.openai_ct},
            )
        if "anthropic" in host:
            return httpx.Response(
                200, content=self.openai_payload,
                headers={"content-type": self.openai_ct},
            )
        return httpx.Response(404, content=b"unknown upstream")


@pytest.mark.asyncio
async def test_e2e_openai_chat_writes_usage_log(
    proxy_db, admin_token, monkeypatch
) -> None:
    """create user → gen key → mock upstream → proxy 呼叫 → usage_log 有 row。"""
    import os
    os.environ["OPENAI_API_KEY"] = "fake-upstream-key"  # 讓 _require_key 過

    # Mock upstream:return 標準 chat completion JSON
    mock_payload = json.dumps({
        "id": "chatcmpl-1",
        "model": "gpt-5-mini",
        "choices": [{"message": {"role": "assistant", "content": "hi"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }).encode()
    transport = _MockUpstreamTransport(mock_payload)

    # Monkey-patch httpx.AsyncClient — 只在沒指定 transport 時注入 mock
    # (test 端 client 自己指定 ASGITransport,不要被覆寫)
    orig_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        if "transport" not in kwargs:
            kwargs["transport"] = transport
        orig_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    app = create_app()

    # 1. admin create user + key
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {admin_token}"},
    ) as c:
        r = await c.post("/admin/users", json={"email": "e2e@x.com"})
        uid = r.json()["id"]
        r = await c.post(f"/admin/users/{uid}/keys", json={"env": "test"})
        token = r.json()["token"]

    # 2. 用 user token 打 proxy /openai/v1/chat/completions
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as c:
        r = await c.post(
            "/openai/v1/chat/completions",
            json={"model": "gpt-5-mini", "messages": [{"role": "user", "content": "hi"}]},
            headers={
                "Authorization": f"Bearer {token}",
                "X-Orion-Client": "test-client",
            },
        )
        assert r.status_code == 200
        assert r.json()["usage"]["completion_tokens"] == 5

    # 3. 等背景 task 寫 DB(create_task)— 給點時間 settle
    for _ in range(10):
        await asyncio.sleep(0.05)
        factory = get_session_factory()
        async with factory() as s:
            rows = (await s.execute(select(UsageLog).where(UsageLog.user_id == uid))).scalars().all()
        if rows:
            break

    assert rows, "usage_log 沒被寫進 DB"
    r = rows[0]
    assert r.provider == "openai"
    assert r.model == "gpt-5-mini"
    assert r.input_tokens == 10
    assert r.output_tokens == 5
    assert r.cost_usd > 0
    assert r.client_id == "test-client"
    # cleanup
    os.environ.pop("OPENAI_API_KEY", None)


@pytest.mark.asyncio
async def test_e2e_anthropic_messages_writes_usage_log(
    proxy_db, admin_token, monkeypatch
) -> None:
    import os
    os.environ["ANTHROPIC_API_KEY"] = "fake-upstream-key"

    mock_payload = json.dumps({
        "id": "msg_1", "model": "claude-haiku-4-5", "role": "assistant",
        "content": [{"type": "text", "text": "hi"}],
        "usage": {"input_tokens": 50, "output_tokens": 10},
    }).encode()
    transport = _MockUpstreamTransport(mock_payload)
    orig_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        if "transport" not in kwargs:
            kwargs["transport"] = transport
        orig_init(self, *args, **kwargs)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {admin_token}"},
    ) as c:
        r = await c.post("/admin/users", json={"email": "ant@x.com"})
        uid = r.json()["id"]
        r = await c.post(f"/admin/users/{uid}/keys", json={"env": "test"})
        token = r.json()["token"]

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as c:
        r = await c.post(
            "/anthropic/v1/messages",
            json={
                "model": "claude-haiku-4-5",
                "max_tokens": 100,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert r.status_code == 200

    # 等寫入
    for _ in range(10):
        await asyncio.sleep(0.05)
        factory = get_session_factory()
        async with factory() as s:
            rows = (
                await s.execute(select(UsageLog).where(UsageLog.user_id == uid))
            ).scalars().all()
        if rows:
            break
    assert rows
    assert rows[0].provider == "anthropic"
    assert rows[0].model == "claude-haiku-4-5"
    assert rows[0].input_tokens == 50
    assert rows[0].output_tokens == 10
    os.environ.pop("ANTHROPIC_API_KEY", None)
