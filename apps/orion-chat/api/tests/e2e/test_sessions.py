"""E:Session CRUD + WS streaming e2e。

驗證:
- POST /sessions 帶 token → 建 session
- GET /sessions 列當前 user 的 sessions
- WS /chat/stream/<sid>?token=... → 送 user message → 收 streaming events

WS 部分用 MockProvider 注入,deterministic + 零 LLM cost。
"""

from __future__ import annotations

import json

import httpx
import pytest
import websockets

from orion_sdk._testing import MockProvider, MockTurn

from .conftest import http_client


pytestmark = pytest.mark.e2e


async def _register_and_login(base: str, username: str = "alice-sess") -> tuple[str, str]:
    """Helper:register + login → (user_id, token)。"""
    async with http_client(base) as c:
        r = await c.post(
            "/auth/register",
            json={"username": username, "password": "passw0rd-ok"},
        )
    user_id = r.json()["user_id"]
    async with http_client(base) as c:
        r = await c.post(
            "/auth/login",
            json={"username": username, "password": "passw0rd-ok"},
        )
    return user_id, r.json()["token"]


@pytest.mark.asyncio
async def test_create_and_list_sessions(chat_api_server, mock_provider_factory) -> None:
    base = chat_api_server["base_url"]
    mock_provider_factory(turns=[]) # 啟 mock provider override
    user_id, token = await _register_and_login(base)

    async with http_client(base, token=token) as c:
        # 先列(應該空)
        r = await c.get("/sessions")
        assert r.status_code == 200
        assert r.json() == []

        # 建 session
        r = await c.post("/sessions", json={})
        assert r.status_code == 201, r.text
        sess = r.json()
        sid = sess["session_id"]
        assert sess["user_id"] == user_id
        assert sess["n_messages"] == 0

        # 再列(應該 1)
        r = await c.get("/sessions")
        assert r.status_code == 200
        listing = r.json()
        assert len(listing) == 1
        assert listing[0]["session_id"] == sid


@pytest.mark.asyncio
async def test_session_requires_auth(chat_api_server) -> None:
    async with http_client(chat_api_server["base_url"]) as c:
        r = await c.post("/sessions", json={})
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_ws_streaming_with_mock_provider(
    chat_api_server, mock_provider_factory
) -> None:
    """End-to-end:WS 送 user message → MockProvider 回 scripted text → 收完整事件流。"""
    base = chat_api_server["base_url"]
    # MockProvider scripted:一個 turn,純 text 結束
    mock_provider_factory(turns=[MockTurn(text="hello from mock")])

    user_id, token = await _register_and_login(base, username="ws-tester")

    # 建 session
    async with http_client(base, token=token) as c:
        r = await c.post("/sessions", json={})
    sid = r.json()["session_id"]

    # WS 連線
    ws_url = base.replace("http://", "ws://") + f"/chat/stream/{sid}?token={token}"
    events: list[dict] = []
    async with websockets.connect(ws_url) as ws:
        # 送 user message
        await ws.send(json.dumps({"type": "user_message", "content": "ping"}))
        # 收事件直到 terminal / error / timeout
        try:
            while True:
                raw = await ws.recv()
                ev = json.loads(raw)
                events.append(ev)
                if ev.get("type") in ("terminal", "error"):
                    break
        except websockets.exceptions.ConnectionClosed:
            pass

    # 驗收 MockProvider 的 scripted text 流到 client
    types = [e.get("type") for e in events]
    text_events = [e for e in events if e.get("type") == "assistant_text"]
    assert text_events, f"missing assistant_text event; got types={types}"
    assert text_events[0]["text"] == "hello from mock"
    assert "turn_complete" in types
    assert "terminal" in types
