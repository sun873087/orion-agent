"""api/auth.py + /auth/login + /me endpoint。"""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from orion_chat_api.app import create_app
from orion_chat_api.auth import (
    dev_user_id,
    issue_token,
    verify_token,
    verify_token_full,
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_issue_and_verify_roundtrip() -> None:
    uid = dev_user_id("alice")
    resp = issue_token(user_id=uid, username="alice")
    assert resp.user_id == uid
    assert resp.username == "alice"
    assert resp.token
    # verify_token 回 sub == user_id
    assert verify_token(resp.token) == uid
    # verify_token_full 同時拿到 username
    identity = verify_token_full(resp.token)
    assert identity.user_id == uid
    assert identity.username == "alice"


def test_dev_user_id_deterministic() -> None:
    """同 username 永遠對到同 UUID(跨 server 重啟仍對齊)。"""
    a1 = dev_user_id("alice")
    a2 = dev_user_id("alice")
    b = dev_user_id("bob")
    assert a1 == a2
    assert a1 != b
    # 而且是合法 UUID 字串
    UUID(a1)


def test_login_endpoint_returns_token(client: TestClient) -> None:
    r = client.post("/auth/login", json={"username": "alice"})
    assert r.status_code == 200
    body = r.json()
    # dev mode user_id 是 deterministic uuid5,不再是 username 字串
    assert body["user_id"] == dev_user_id("alice")
    assert body["username"] == "alice"
    assert body["token"]
    assert body["expires_at"]


def test_login_empty_username_rejected(client: TestClient) -> None:
    r = client.post("/auth/login", json={"username": ""})
    assert r.status_code == 422


def test_invalid_token_raises() -> None:
    import jwt
    with pytest.raises(jwt.InvalidTokenError):
        verify_token("not.a.token")


def test_legacy_token_without_username_claim_rejected() -> None:
    """/7 token(sub=username,沒 username claim)→ 401 強制重 login。"""
    import jwt as pyjwt

    from orion_chat_api import auth as auth_mod

    legacy = pyjwt.encode(
        {"sub": "alice", "iat": 0, "exp": 9999999999},
        auth_mod._get_secret(),
        algorithm="HS256",
    )
    with pytest.raises(pyjwt.InvalidTokenError):
        verify_token(legacy)


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
    assert r.json() == [] # 沒 session


def test_me_endpoint_returns_identity(client: TestClient) -> None:
    """GET /me 從 token claim 取 user_id + username,不打 DB。"""
    login = client.post("/auth/login", json={"username": "alice"}).json()
    r = client.get("/me", headers={"Authorization": f"Bearer {login['token']}"})
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == dev_user_id("alice")
    assert body["username"] == "alice"


def test_me_endpoint_requires_token(client: TestClient) -> None:
    r = client.get("/me")
    assert r.status_code in (401, 403)
