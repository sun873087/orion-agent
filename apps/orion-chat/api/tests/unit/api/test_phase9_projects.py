"""Phase 9 — projects CRUD + session 關聯。

per-project system-prompt 注入與 workspace sandbox 留待後續(見路線圖)。
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


def test_project_crud_and_session_link(
    two_users: tuple[TestClient, str, str],
) -> None:
    client, at, _ = two_users
    pid = client.post(
        "/projects",
        headers=_h(at),
        json={"name": "Research", "custom_instructions": "Cite sources."},
    ).json()["id"]
    listing = client.get("/projects", headers=_h(at)).json()
    assert any(p["id"] == pid and p["name"] == "Research" for p in listing)

    # 關聯 session
    sid = client.post("/sessions", headers=_h(at)).json()["session_id"]
    r = client.put(
        f"/sessions/{sid}/project", headers=_h(at), json={"project_id": pid},
    )
    assert r.status_code == 200 and r.json()["project_id"] == pid

    # 刪 project
    assert client.delete(f"/projects/{pid}", headers=_h(at)).json() == {
        "deleted": True,
    }
    assert all(p["id"] != pid for p in client.get("/projects", headers=_h(at)).json())


def test_project_cross_user_isolation(
    two_users: tuple[TestClient, str, str],
) -> None:
    client, at, bt = two_users
    pid = client.post(
        "/projects", headers=_h(at), json={"name": "secret"},
    ).json()["id"]
    # bob 看不到 alice 的 project
    assert all(
        p["id"] != pid for p in client.get("/projects", headers=_h(bt)).json()
    )
    # bob 不能刪 / 改
    assert client.delete(f"/projects/{pid}", headers=_h(bt)).status_code == 404
