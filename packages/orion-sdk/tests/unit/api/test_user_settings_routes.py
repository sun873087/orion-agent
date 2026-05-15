"""/me/settings REST CRUD。Phase 14。"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from orion_chat_api.app import create_app


@pytest.fixture
def client_with_token(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, str]]:
    """設 ORION_DB_URL 起 in-memory SQLite + 自動 init_db,login 拿 token。

    用 `with TestClient(...)` 觸發 lifespan(才會建 db_engine);否則 endpoints 503。
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key")
    monkeypatch.setenv("ORION_PROVIDER", "anthropic")
    monkeypatch.setenv("ORION_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("ORION_DB_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("ORION_DB_AUTO_CREATE", "1")
    with TestClient(create_app()) as client:
        # DB mode 必註冊再 login
        client.post(
            "/auth/register", json={"username": "alice", "password": "passw0rd"},
        )
        login = client.post(
            "/auth/login", json={"username": "alice", "password": "passw0rd"},
        ).json()
        yield client, login["token"]


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_get_all_empty(client_with_token: tuple[TestClient, str]) -> None:
    client, token = client_with_token
    r = client.get("/me/settings", headers=_h(token))
    assert r.status_code == 200
    assert r.json() == {}


def test_put_creates_with_version_1(
    client_with_token: tuple[TestClient, str],
) -> None:
    client, token = client_with_token
    r = client.put(
        "/me/settings/model",
        headers=_h(token),
        json={"value": "claude-opus-4-7"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["key"] == "model"
    assert body["value"] == "claude-opus-4-7"
    assert body["version"] == 1


def test_get_after_put(client_with_token: tuple[TestClient, str]) -> None:
    client, token = client_with_token
    client.put(
        "/me/settings/lang", headers=_h(token), json={"value": "zh-TW"},
    )
    r = client.get("/me/settings/lang", headers=_h(token))
    assert r.status_code == 200
    assert r.json() == {"key": "lang", "value": "zh-TW", "version": 1}


def test_get_all_returns_dict(client_with_token: tuple[TestClient, str]) -> None:
    client, token = client_with_token
    client.put("/me/settings/a", headers=_h(token), json={"value": 1})
    client.put("/me/settings/b", headers=_h(token), json={"value": [1, 2, 3]})
    r = client.get("/me/settings", headers=_h(token))
    assert r.status_code == 200
    assert r.json() == {"a": 1, "b": [1, 2, 3]}


def test_put_increments_version(
    client_with_token: tuple[TestClient, str],
) -> None:
    client, token = client_with_token
    client.put("/me/settings/k", headers=_h(token), json={"value": "v1"})
    r = client.put(
        "/me/settings/k", headers=_h(token),
        json={"value": "v2", "expected_version": 1},
    )
    assert r.status_code == 200
    assert r.json()["version"] == 2


def test_put_optimistic_conflict(
    client_with_token: tuple[TestClient, str],
) -> None:
    """expected_version 不對 → 409。"""
    client, token = client_with_token
    client.put("/me/settings/k", headers=_h(token), json={"value": "v1"})
    r = client.put(
        "/me/settings/k", headers=_h(token),
        json={"value": "v2", "expected_version": 99},
    )
    assert r.status_code == 409
    assert "Version conflict" in r.json()["detail"]


def test_put_without_expected_version_overwrites(
    client_with_token: tuple[TestClient, str],
) -> None:
    """沒帶 expected_version → 不檢查,直接覆蓋(version 仍 +1)。"""
    client, token = client_with_token
    client.put("/me/settings/k", headers=_h(token), json={"value": "v1"})
    r = client.put("/me/settings/k", headers=_h(token), json={"value": "v2"})
    assert r.status_code == 200
    assert r.json()["version"] == 2


def test_get_nonexistent_returns_404(
    client_with_token: tuple[TestClient, str],
) -> None:
    client, token = client_with_token
    r = client.get("/me/settings/never-set", headers=_h(token))
    assert r.status_code == 404


def test_delete(client_with_token: tuple[TestClient, str]) -> None:
    client, token = client_with_token
    client.put("/me/settings/k", headers=_h(token), json={"value": 1})
    r = client.delete("/me/settings/k", headers=_h(token))
    assert r.status_code == 200
    assert r.json() == {"deleted": True}
    # 已刪
    r2 = client.get("/me/settings/k", headers=_h(token))
    assert r2.status_code == 404


def test_delete_nonexistent_idempotent(
    client_with_token: tuple[TestClient, str],
) -> None:
    client, token = client_with_token
    r = client.delete("/me/settings/never", headers=_h(token))
    assert r.status_code == 200
    assert r.json() == {"deleted": False}


def test_complex_value(client_with_token: tuple[TestClient, str]) -> None:
    """value 可以是任何 JSON 結構。"""
    client, token = client_with_token
    payload = {
        "ui": {"theme": "dark", "fontSize": 14},
        "permissions": [{"tool": "Bash", "decision": "allow"}],
    }
    client.put("/me/settings/prefs", headers=_h(token), json={"value": payload})
    r = client.get("/me/settings/prefs", headers=_h(token))
    assert r.json()["value"] == payload


def test_unauthorized_no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORION_DB_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("ORION_DB_AUTO_CREATE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    with TestClient(create_app()) as client:
        r = client.get("/me/settings")
        # FastAPI HTTPBearer(auto_error=True) 沒 Authorization header 回 401
        # (不同 Starlette / FastAPI 版本可能 401 或 403,允許兩者)
        assert r.status_code in (401, 403)


def test_no_db_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """沒設 ORION_DB_URL → 503。"""
    monkeypatch.delenv("ORION_DB_URL", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    with TestClient(create_app()) as client:
        login = client.post("/auth/login", json={"username": "bob"}).json()
        r = client.get("/me/settings", headers=_h(login["token"]))
        assert r.status_code == 503
