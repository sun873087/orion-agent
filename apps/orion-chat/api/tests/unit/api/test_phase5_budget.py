"""Phase 5 — per-session budget cap。

超額→abort 與 auto-compact 是 turn/WS 驅動(mock 成本=0,無法 e2e 觸發),
這裡測 budget GET/PUT round-trip + 跨 user 隔離 + 純判定 helper。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orion_chat_api.app import create_app
from orion_chat_api.conversation_meta import budget_is_exceeded


def test_budget_is_exceeded_helper() -> None:
    assert budget_is_exceeded(1.0, None) is False
    assert budget_is_exceeded(0.5, 1.0) is False
    assert budget_is_exceeded(1.0, 1.0) is True
    assert budget_is_exceeded(2.0, 1.0) is True


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


def test_budget_get_put_roundtrip(two_users: tuple[TestClient, str, str]) -> None:
    client, at, _ = two_users
    sid = client.post("/sessions", headers=_h(at)).json()["session_id"]
    # 預設無上限
    assert client.get(f"/sessions/{sid}/budget", headers=_h(at)).json() == {
        "budget_usd_cap": None,
        "budget_exceeded": False,
    }
    # 設上限
    r = client.put(
        f"/sessions/{sid}/budget", headers=_h(at), json={"budget_usd_cap": 5.0},
    )
    assert r.status_code == 200
    assert r.json()["budget_usd_cap"] == 5.0
    assert client.get(f"/sessions/{sid}/budget", headers=_h(at)).json()[
        "budget_usd_cap"
    ] == 5.0


def test_budget_cross_user_404(two_users: tuple[TestClient, str, str]) -> None:
    client, at, bt = two_users
    sid = client.post("/sessions", headers=_h(at)).json()["session_id"]
    assert (
        client.put(
            f"/sessions/{sid}/budget", headers=_h(bt), json={"budget_usd_cap": 1.0},
        ).status_code
        == 404
    )
