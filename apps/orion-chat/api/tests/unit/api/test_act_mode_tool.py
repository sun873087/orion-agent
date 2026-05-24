"""Regression:act 模式下工具呼叫不可因 can_use_tool=None 而 crash。

Phase 7 曾把 act 模式的 conv.can_use_tool 設成 None,但 SDK tool_execution 會無條件
`await can_use_tool(...)` → TypeError。需 DB-backed manager(才會跑 permission_mode
分支)+ 一個會呼工具的 turn 才會觸發。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from orion_chat_api.app import create_app


def test_act_mode_tool_call_does_not_crash(
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
        # lifespan 後覆蓋成會呼工具的 mock(turn1 呼 Glob,turn2 收尾)
        client.app.state.llm_provider = MockProvider(
            turns=[
                MockTurn(
                    text="listing",
                    tool_uses=[("g1", "Glob", {"pattern": "*"})],
                ),
                MockTurn(text="done"),
            ],
        )
        client.post("/auth/register", json={"username": "a", "password": "pw123456"})
        token = client.post(
            "/auth/login", json={"username": "a", "password": "pw123456"},
        ).json()["token"]
        h = {"Authorization": f"Bearer {token}"}
        sid = client.post("/sessions", headers=h).json()["session_id"]
        assert (
            client.put(
                f"/sessions/{sid}/permission-mode", headers=h, json={"mode": "act"},
            ).status_code
            == 200
        )

        with client.websocket_connect(f"/chat/stream/{sid}?token={token}") as ws:
            assert ws.receive_json()["type"] == "history_replay_done"
            ws.send_json({"type": "user_message", "content": "go"})
            events: list[dict[str, Any]] = []
            while True:
                ev = ws.receive_json()
                events.append(ev)
                if ev["type"] == "terminal":
                    break

    # 不該出現 can_use_tool=None 造成的 NoneType crash
    errors = [e["message"] for e in events if e["type"] == "error"]
    assert not any(
        "not callable" in m or "NoneType" in m for m in errors
    ), errors
    # 工具有走到 permission + 執行(act 全放行)→ 有 tool_result
    assert any(e["type"] == "tool_result" and e.get("tool_use_id") == "g1" for e in events)
