"""full e2e:create user → gen key → make request → log row →
admin 看到 rollup → budget cap 觸發 402。"""

from __future__ import annotations

import asyncio
import json
import os

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from orion_model_proxy.server import create_app


class _MockOk(httpx.AsyncBaseTransport):
    def __init__(self, payload: bytes):
        self.payload = payload

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=self.payload,
            headers={"content-type": "application/json"},
        )


@pytest.mark.asyncio
async def test_complete_lifecycle(proxy_db, admin_token, monkeypatch) -> None:
    """端到端:admin → user → key → request → DB → rollup → 達 cap → 402。"""
    os.environ["OPENAI_API_KEY"] = "fake-upstream"
    # 用大 token 量讓單次 cost(~$0.0075)就超 $0.001 cap → 第二次 request 必 402
    payload = json.dumps({
        "id": "x", "model": "gpt-5-mini",
        "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        "usage": {"prompt_tokens": 10000, "completion_tokens": 5000},
    }).encode()
    transport = _MockOk(payload)
    orig_init = httpx.AsyncClient.__init__

    def patched(self, *args, **kwargs):
        if "transport" not in kwargs:
            kwargs["transport"] = transport
        orig_init(self, *args, **kwargs)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)

    app = create_app()
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # ① Admin REST 建 user(設 $0.001 超小 cap)+ 拿 token
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        headers=admin_headers,
    ) as c:
        r = await c.post(
            "/admin/users",
            json={"email": "e2e@x.com", "display_name": "E2E", "budget_usd": 0.001},
        )
        assert r.status_code == 201
        uid = r.json()["id"]

        r = await c.post(f"/admin/users/{uid}/keys", json={"env": "test"})
        token = r.json()["token"]
        assert token.startswith("sk-orion-test-")

        # ② Admin REST usage rollup — 初始全 0
        r = await c.get(f"/admin/users/{uid}/usage")
        assert r.json()["total_cost_usd"] == 0.0
        assert r.json()["request_count"] == 0

    # ③ 用 user token 打 proxy /openai/v1/chat/completions
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as c:
        r = await c.post(
            "/openai/v1/chat/completions",
            json={"model": "gpt-5-mini", "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Orion-Client": "test-cli"},
        )
        assert r.status_code == 200

    # 等背景 usage_log task 寫完
    for _ in range(20):
        await asyncio.sleep(0.05)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
            headers=admin_headers,
        ) as c:
            r = await c.get(f"/admin/users/{uid}/usage")
            if r.json()["request_count"] > 0:
                break

    # ④ Admin REST 看 rollup — 有 1 筆 + 對應 cost
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        headers=admin_headers,
    ) as c:
        r = await c.get(f"/admin/users/{uid}/usage")
        u = r.json()
        assert u["request_count"] == 1
        assert u["total_cost_usd"] > 0
        assert "gpt-5-mini" in u["by_model"]

    # ⑤ 第二次 request — 應該因為 cost > $0.001 被擋 402
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as c:
        r = await c.post(
            "/openai/v1/chat/completions",
            json={"model": "gpt-5-mini", "messages": []},
        )
        assert r.status_code == 402, f"expected 402 over budget, got {r.status_code}: {r.text}"

    # ⑥ Admin UI 也能看到這個 user
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as c:
        await c.post("/admin/ui/login", data={"token": admin_token})
        r = await c.get("/admin/ui/users")
        assert "e2e@x.com" in r.text
        assert "⚠ over" in r.text # banner 提示超 cap

    os.environ.pop("OPENAI_API_KEY", None)
