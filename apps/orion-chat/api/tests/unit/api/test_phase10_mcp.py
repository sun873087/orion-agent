"""Phase 10 — per-user MCP server 設定 CRUD(remote-only)。"""

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


def test_mcp_crud_and_remote_only(two_users: tuple[TestClient, str, str]) -> None:
    client, at, _ = two_users
    assert client.get("/mcp/servers", headers=_h(at)).json() == []
    r = client.put(
        "/mcp/servers/docs",
        headers=_h(at),
        json={"transport": "http", "url": "https://mcp.example.com"},
    )
    assert r.status_code == 200 and r.json()["transport"] == "http"
    assert any(
        s["name"] == "docs" for s in client.get("/mcp/servers", headers=_h(at)).json()
    )
    # stdio 被拒
    assert (
        client.put(
            "/mcp/servers/local",
            headers=_h(at),
            json={"transport": "stdio", "url": "x"},
        ).status_code
        == 422
    )
    # delete
    assert client.delete("/mcp/servers/docs", headers=_h(at)).json() == {
        "deleted": True,
    }


def test_mcp_per_user_isolation(two_users: tuple[TestClient, str, str]) -> None:
    client, at, bt = two_users
    client.put(
        "/mcp/servers/secret",
        headers=_h(at),
        json={"transport": "sse", "url": "https://x"},
    )
    assert client.get("/mcp/servers", headers=_h(bt)).json() == []
