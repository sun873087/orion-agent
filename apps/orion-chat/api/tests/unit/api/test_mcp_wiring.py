"""MCP 真的接進 agent:remote http config 載入(禁 stdio),且連不上不擋對話。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from orion_chat_api.app import create_app


def test_loader_keeps_http_drops_stdio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("ORION_USERS_DIR", str(tmp_path / "users"))
    from orion_chat_api.mcp_loader import _mcp_path, load_user_http_mcp_configs

    p = _mcp_path("u1")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "servers": {
                    "remote": {"transport": "http", "url": "https://example.com/mcp"},
                    "streamed": {"transport": "sse", "url": "https://x.com/sse"},
                    "local": {"transport": "stdio", "command": "echo"},
                },
            },
        ),
        encoding="utf-8",
    )
    configs = load_user_http_mcp_configs("u1")
    # 只留 http;stdio(禁)+ sse(SDK 尚無 transport)都不在
    assert set(configs) == {"remote"}
    assert configs["remote"].url == "https://example.com/mcp"


def test_unreachable_mcp_does_not_break_chat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from orion_sdk._testing import MockProvider, MockTurn

    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key")
    monkeypatch.setenv("ORION_PROVIDER", "anthropic")
    monkeypatch.setenv("ORION_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("ORION_DB_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("ORION_DB_AUTO_CREATE", "1")
    monkeypatch.setenv("ORION_USERS_DIR", str(tmp_path / "users"))

    app = create_app()
    with TestClient(app) as client:
        client.app.state.llm_provider = MockProvider(turns=[MockTurn(text="ok")])
        client.post("/auth/register", json={"username": "a", "password": "pw123456"})
        token = client.post(
            "/auth/login", json={"username": "a", "password": "pw123456"},
        ).json()["token"]
        h = {"Authorization": f"Bearer {token}"}
        sid = client.post("/sessions", headers=h).json()["session_id"]

        # 設一個連不上的 remote MCP(connection refused,快速失敗)
        client.put(
            "/mcp/servers/dead",
            headers=h,
            json={"type": "http", "url": "http://127.0.0.1:1/mcp"},
        )

        with client.websocket_connect(f"/chat/stream/{sid}?token={token}") as ws:
            assert ws.receive_json()["type"] == "history_replay_done"
            ws.send_json({"type": "user_message", "content": "hi"})
            events: list[dict[str, Any]] = []
            while True:
                ev = ws.receive_json()
                events.append(ev)
                if ev["type"] == "terminal":
                    break

    # MCP 連不上不該炸 — 對話照常完成,沒有 server error
    errors = [e["message"] for e in events if e["type"] == "error"]
    assert not any("server error" in m for m in errors), errors
