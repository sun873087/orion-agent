"""Phase 4 — context breakdown(讀)。

cost breakdown 沿用既有 /cost 的 by_model;turn audit / message feedback 因架構
(WS 串流無穩定 message id、SDK 未 expose wire payload)延後,見路線圖。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orion_chat_api.app import create_app


@pytest.fixture
def client_with_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> Iterator[tuple[TestClient, str]]:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key")
    monkeypatch.setenv("ORION_PROVIDER", "anthropic")
    monkeypatch.setenv("ORION_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("ORION_DB_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("ORION_DB_AUTO_CREATE", "1")
    monkeypatch.setenv("ORION_USERS_DIR", str(tmp_path / "users"))
    with TestClient(create_app()) as client:
        client.post("/auth/register", json={"username": "alice", "password": "pw123456"})
        token = client.post(
            "/auth/login", json={"username": "alice", "password": "pw123456"},
        ).json()["token"]
        yield client, token


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_context_breakdown_shape(
    client_with_token: tuple[TestClient, str],
) -> None:
    client, token = client_with_token
    sid = client.post("/sessions", headers=_h(token)).json()["session_id"]
    r = client.get(f"/sessions/{sid}/context-breakdown", headers=_h(token))
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["n_messages"] == 0
    assert body["by_role_chars"] == {}
    assert isinstance(body["approx_total_tokens"], int)
    assert body["approx_total_tokens"] >= 0


def test_context_breakdown_404_for_missing(
    client_with_token: tuple[TestClient, str],
) -> None:
    client, token = client_with_token
    r = client.get(
        "/sessions/00000000-0000-0000-0000-000000000000/context-breakdown",
        headers=_h(token),
    )
    assert r.status_code == 404
