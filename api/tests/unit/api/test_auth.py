"""api/auth.py + /auth/login endpoint。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from orion_agent.api.app import create_app
from orion_agent.api.auth import issue_token, verify_token


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_issue_and_verify_roundtrip() -> None:
    resp = issue_token("alice")
    assert resp.user_id == "alice"
    assert resp.token
    assert verify_token(resp.token) == "alice"


def test_login_endpoint_returns_token(client: TestClient) -> None:
    r = client.post("/auth/login", json={"username": "alice"})
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == "alice"
    assert body["token"]
    assert body["expires_at"]


def test_login_empty_username_rejected(client: TestClient) -> None:
    r = client.post("/auth/login", json={"username": ""})
    assert r.status_code == 422


def test_invalid_token_raises() -> None:
    import jwt
    with pytest.raises(jwt.InvalidTokenError):
        verify_token("not.a.token")


def test_protected_endpoint_requires_bearer(client: TestClient) -> None:
    r = client.get("/sessions")
    assert r.status_code in (401, 403)


def test_protected_endpoint_with_token(client: TestClient) -> None:
    login = client.post("/auth/login", json={"username": "alice"}).json()
    r = client.get(
        "/sessions",
        headers={"Authorization": f"Bearer {login['token']}"},
    )
    assert r.status_code == 200
    assert r.json() == []  # 沒 session
