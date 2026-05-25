"""Roles / Projects 真的接進 agent — active role 的 ROLE.md body 與 project
custom_instructions 必須出現在送給 provider 的 system prompt(不再是空殼)。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from orion_chat_api.app import create_app


def _setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key")
    monkeypatch.setenv("ORION_PROVIDER", "anthropic")
    monkeypatch.setenv("ORION_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("ORION_DB_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("ORION_DB_AUTO_CREATE", "1")
    monkeypatch.setenv("ORION_USERS_DIR", str(tmp_path / "users"))
    monkeypatch.setenv("ORION_USER_ROLES_DIR", str(tmp_path / "users"))
    monkeypatch.setenv("ORION_USER_SKILLS_DIR", str(tmp_path / "users"))
    monkeypatch.setenv("ORION_SKILLS_DIR", str(tmp_path / "system_skills"))


def test_role_and_project_injected_into_system_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from orion_sdk._testing import MockProvider, MockTurn

    _setup(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        client.app.state.llm_provider = MockProvider(turns=[MockTurn(text="aye")])
        client.post("/auth/register", json={"username": "a", "password": "pw123456"})
        token = client.post(
            "/auth/login", json={"username": "a", "password": "pw123456"},
        ).json()["token"]
        h = {"Authorization": f"Bearer {token}"}

        # role(ROLE.md body 帶獨特 marker)
        assert client.put(
            "/roles/pirate",
            headers=h,
            json={"description": "arr", "body": "ROLEMARKER speak like a pirate"},
        ).status_code in (200, 201)
        # project(custom_instructions 帶獨特 marker)
        pid = client.post(
            "/projects",
            headers=h,
            json={"name": "P", "custom_instructions": "PROJMARKER reply in JSON"},
        ).json()["id"]

        sid = client.post("/sessions", headers=h).json()["session_id"]
        assert (
            client.put(
                f"/sessions/{sid}/role", headers=h, json={"role": "pirate"},
            ).status_code
            == 200
        )
        assert (
            client.put(
                f"/sessions/{sid}/project", headers=h, json={"project_id": pid},
            ).status_code
            == 200
        )

        with client.websocket_connect(f"/chat/stream/{sid}?token={token}") as ws:
            assert ws.receive_json()["type"] == "history_replay_done"
            ws.send_json({"type": "user_message", "content": "hi"})
            while True:
                if ws.receive_json()["type"] == "terminal":
                    break

    provider: Any = client.app.state.llm_provider
    assert provider.captured_calls, "provider never called"
    sys = provider.captured_calls[0]["system"]
    sys_text = sys if isinstance(sys, str) else "\n".join(sys)
    assert "ROLEMARKER" in sys_text, "role body not injected into system prompt"
    assert "PROJMARKER" in sys_text, "project instructions not injected"


def test_custom_instructions_injected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """「指令」面板的 user-level custom instructions 要進 system prompt(對齊 Cowork:只一層)。"""
    from orion_sdk._testing import MockProvider, MockTurn

    _setup(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        client.app.state.llm_provider = MockProvider(turns=[MockTurn(text="ok")])
        client.post("/auth/register", json={"username": "a", "password": "pw123456"})
        token = client.post(
            "/auth/login", json={"username": "a", "password": "pw123456"},
        ).json()["token"]
        h = {"Authorization": f"Bearer {token}"}

        client.put(
            "/me/custom-instructions",
            headers=h,
            json={"instructions": "USERINST be concise"},
        )
        sid = client.post("/sessions", headers=h).json()["session_id"]

        with client.websocket_connect(f"/chat/stream/{sid}?token={token}") as ws:
            assert ws.receive_json()["type"] == "history_replay_done"
            ws.send_json({"type": "user_message", "content": "hi"})
            while True:
                if ws.receive_json()["type"] == "terminal":
                    break

    provider: Any = client.app.state.llm_provider
    sys = provider.captured_calls[0]["system"]
    sys_text = sys if isinstance(sys, str) else "\n".join(sys)
    assert "USERINST" in sys_text, "user-level custom instructions not injected"


def test_put_unknown_role_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _setup(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        client.post("/auth/register", json={"username": "a", "password": "pw123456"})
        token = client.post(
            "/auth/login", json={"username": "a", "password": "pw123456"},
        ).json()["token"]
        h = {"Authorization": f"Bearer {token}"}
        sid = client.post("/sessions", headers=h).json()["session_id"]
        r = client.put(
            f"/sessions/{sid}/role", headers=h, json={"role": "no-such-role"},
        )
        assert r.status_code == 422
