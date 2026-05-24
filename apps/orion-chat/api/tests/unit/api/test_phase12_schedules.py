"""Phase 12 — schedules CRUD + cron 引擎。背景 firing daemon 留待後續(見路線圖)。"""

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


def test_schedule_crud_and_cron_validation(
    two_users: tuple[TestClient, str, str],
) -> None:
    client, at, _ = two_users
    r = client.post(
        "/schedules",
        headers=_h(at),
        json={"name": "Daily", "cron_expr": "0 9 * * *", "payload": "summarise"},
    )
    assert r.status_code == 201, r.json()
    sid = r.json()["id"]
    assert r.json()["next_run_at"] is not None  # cron 算出下次時間

    assert any(s["id"] == sid for s in client.get("/schedules", headers=_h(at)).json())

    # 壞 cron → 422
    assert (
        client.post(
            "/schedules",
            headers=_h(at),
            json={"name": "bad", "cron_expr": "not a cron"},
        ).status_code
        == 422
    )

    assert client.delete(f"/schedules/{sid}", headers=_h(at)).json() == {
        "deleted": True,
    }


def test_schedule_cross_user_isolation(
    two_users: tuple[TestClient, str, str],
) -> None:
    client, at, bt = two_users
    sid = client.post(
        "/schedules",
        headers=_h(at),
        json={"name": "x", "cron_expr": "* * * * *"},
    ).json()["id"]
    assert all(
        s["id"] != sid for s in client.get("/schedules", headers=_h(bt)).json()
    )
    assert client.delete(f"/schedules/{sid}", headers=_h(bt)).status_code == 404
