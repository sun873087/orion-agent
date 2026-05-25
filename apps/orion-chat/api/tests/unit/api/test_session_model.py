"""PUT /sessions/{sid}/model — 就地切換既有 session 的 model(歷史保留)。"""

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
        client.post("/auth/register", json={"username": "a", "password": "pw123456"})
        token = client.post(
            "/auth/login", json={"username": "a", "password": "pw123456"},
        ).json()["token"]
        yield client, token


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_switch_model_in_place(
    client_with_token: tuple[TestClient, str],
) -> None:
    client, token = client_with_token
    sid = client.post("/sessions", headers=_h(token)).json()["session_id"]

    r = client.put(
        f"/sessions/{sid}/model",
        headers=_h(token),
        json={"provider": "anthropic", "model": "claude-haiku-4-5"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # 同一個 session_id,model 換掉
    assert body["session_id"] == sid
    assert body["model"] == "claude-haiku-4-5"

    # GET 重讀也是新 model(in-memory cache + DB row 都更新)
    got = client.get(f"/sessions/{sid}", headers=_h(token)).json()
    assert got["model"] == "claude-haiku-4-5"


def test_switch_model_rejects_invalid(
    client_with_token: tuple[TestClient, str],
) -> None:
    client, token = client_with_token
    sid = client.post("/sessions", headers=_h(token)).json()["session_id"]
    r = client.put(
        f"/sessions/{sid}/model",
        headers=_h(token),
        json={"provider": "anthropic", "model": "no-such-model"},
    )
    assert r.status_code == 422


def test_switch_model_cross_user_404(
    client_with_token: tuple[TestClient, str],
) -> None:
    client, token = client_with_token
    sid = client.post("/sessions", headers=_h(token)).json()["session_id"]
    client.post("/auth/register", json={"username": "b", "password": "pw123456"})
    other = client.post(
        "/auth/login", json={"username": "b", "password": "pw123456"},
    ).json()["token"]
    r = client.put(
        f"/sessions/{sid}/model",
        headers=_h(other),
        json={"provider": "anthropic", "model": "claude-haiku-4-5"},
    )
    assert r.status_code == 404
