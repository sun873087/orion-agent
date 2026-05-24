"""Phase 14 — collaborations CRUD + pane 關聯。

跨 pane DispatchPane 執行 + MultiPaneView 並排即時渲染留待後續(見路線圖,需背景
turn 注入)。限同一 user。
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


def test_collaboration_crud_and_add_pane(
    two_users: tuple[TestClient, str, str],
) -> None:
    client, at, _ = two_users
    cid = client.post(
        "/collaborations", headers=_h(at), json={"name": "Squad"},
    ).json()["id"]

    sid = client.post("/sessions", headers=_h(at)).json()["session_id"]
    r = client.put(
        f"/collaborations/{cid}/panes",
        headers=_h(at),
        json={"session_id": sid},
    )
    assert r.status_code == 200, r.json()
    assert sid in r.json()["pane_session_ids"]

    listing = client.get("/collaborations", headers=_h(at)).json()
    me = next(c for c in listing if c["id"] == cid)
    assert me["pane_session_ids"] == [sid]

    assert client.delete(f"/collaborations/{cid}", headers=_h(at)).json() == {
        "deleted": True,
    }


def test_collaboration_cross_user(two_users: tuple[TestClient, str, str]) -> None:
    client, at, bt = two_users
    cid = client.post(
        "/collaborations", headers=_h(at), json={"name": "x"},
    ).json()["id"]
    assert all(
        c["id"] != cid for c in client.get("/collaborations", headers=_h(bt)).json()
    )
    assert client.delete(f"/collaborations/{cid}", headers=_h(bt)).status_code == 404
