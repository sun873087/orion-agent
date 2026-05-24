"""Phase 7 — per-session permission mode(ask / act)。

持久跨 session tool policy(always_allow 寫檔)延後;這裡測 per-session mode 切換。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orion_chat_api.app import create_app


@pytest.fixture
def two_users(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> Iterator[tuple[TestClient, str, str]]:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key")
    monkeypatch.setenv("ORION_PROVIDER", "anthropic")
    monkeypatch.setenv("ORION_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("ORION_DB_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("ORION_DB_AUTO_CREATE", "1")
    monkeypatch.setenv("ORION_USERS_DIR", str(tmp_path / "users"))
    with TestClient(create_app()) as client:
        for u in ("alice", "bob"):
            client.post("/auth/register", json={"username": u, "password": "pw123456"})
        at = client.post(
            "/auth/login", json={"username": "alice", "password": "pw123456"},
        ).json()["token"]
        bt = client.post(
            "/auth/login", json={"username": "bob", "password": "pw123456"},
        ).json()["token"]
        yield client, at, bt


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_permission_mode_defaults_ask_and_toggles(
    two_users: tuple[TestClient, str, str],
) -> None:
    client, at, _ = two_users
    sid = client.post("/sessions", headers=_h(at)).json()["session_id"]
    assert client.get(
        f"/sessions/{sid}/permission-mode", headers=_h(at),
    ).json() == {"mode": "ask"}
    r = client.put(
        f"/sessions/{sid}/permission-mode", headers=_h(at), json={"mode": "act"},
    )
    assert r.status_code == 200 and r.json()["mode"] == "act"
    assert client.get(
        f"/sessions/{sid}/permission-mode", headers=_h(at),
    ).json() == {"mode": "act"}


def test_permission_mode_rejects_bad_value(
    two_users: tuple[TestClient, str, str],
) -> None:
    client, at, _ = two_users
    sid = client.post("/sessions", headers=_h(at)).json()["session_id"]
    r = client.put(
        f"/sessions/{sid}/permission-mode", headers=_h(at), json={"mode": "yolo"},
    )
    assert r.status_code == 422


def test_permission_mode_cross_user_404(
    two_users: tuple[TestClient, str, str],
) -> None:
    client, at, bt = two_users
    sid = client.post("/sessions", headers=_h(at)).json()["session_id"]
    assert (
        client.put(
            f"/sessions/{sid}/permission-mode", headers=_h(bt), json={"mode": "act"},
        ).status_code
        == 404
    )
