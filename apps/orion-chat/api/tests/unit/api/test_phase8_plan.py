"""Phase 8 — plan mode 狀態機。

模型自動 call EnterPlanMode/ExitPlanMode 的整合延後;這裡測 host/UI 驅動的
enter → submit → approve / reject 轉換 + 跨 user 隔離。enforcement(唯讀/全擋)
由 chat.py 套 SDK plan_mode_aware,屬 turn 層,這裡不觸發。
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


def test_plan_state_machine(two_users: tuple[TestClient, str, str]) -> None:
    client, at, _ = two_users
    sid = client.post("/sessions", headers=_h(at)).json()["session_id"]
    base = f"/sessions/{sid}/plan"

    assert client.get(f"{base}/status", headers=_h(at)).json()["status"] == "inactive"
    assert client.post(f"{base}/enter", headers=_h(at)).json()["status"] == "active"
    r = client.post(
        f"{base}/submit", headers=_h(at), json={"content": "# Plan\n1. do it"},
    )
    assert r.json()["status"] == "awaiting_approval"
    assert "do it" in client.get(f"{base}/status", headers=_h(at)).json()["content"]
    # reject → 回 active 並清掉草稿
    assert client.post(f"{base}/reject", headers=_h(at)).json()["status"] == "active"
    assert client.get(f"{base}/status", headers=_h(at)).json()["content"] == ""
    # submit 再 approve → inactive
    client.post(f"{base}/submit", headers=_h(at), json={"content": "x"})
    assert client.post(f"{base}/approve", headers=_h(at)).json()["status"] == "inactive"


def test_plan_cross_user_404(two_users: tuple[TestClient, str, str]) -> None:
    client, at, bt = two_users
    sid = client.post("/sessions", headers=_h(at)).json()["session_id"]
    assert (
        client.post(f"/sessions/{sid}/plan/enter", headers=_h(bt)).status_code == 404
    )
