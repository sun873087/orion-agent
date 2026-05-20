"""E:基礎 e2e — health + register/login flow。

驗證 chat-api 真的能起 + auth flow 通(寫進 DB → 拿 JWT → /me 帶 token 回 user)。
不涉及 WS / LLM,完全 deterministic。
"""

from __future__ import annotations

import pytest

from .conftest import http_client


pytestmark = pytest.mark.e2e


@pytest.mark.asyncio
async def test_healthz(chat_api_server) -> None:
    async with http_client(chat_api_server["base_url"]) as c:
        r = await c.get("/healthz")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


@pytest.mark.asyncio
async def test_register_login_me_flow(chat_api_server) -> None:
    base = chat_api_server["base_url"]
    username = "alice-e2e"
    password = "strong-password-123"

    # 1. Register
    async with http_client(base) as c:
        r = await c.post("/auth/register", json={"username": username, "password": password})
    assert r.status_code == 201, r.text
    user_id = r.json()["user_id"]
    assert r.json()["username"] == username

    # 2. Login
    async with http_client(base) as c:
        r = await c.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    assert token
    assert r.json()["user_id"] == user_id
    assert r.json()["username"] == username

    # 3. /me with token
    async with http_client(base, token=token) as c:
        r = await c.get("/me")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["username"] == username
    assert body["user_id"] == user_id


@pytest.mark.asyncio
async def test_register_duplicate_username(chat_api_server) -> None:
    base = chat_api_server["base_url"]
    payload = {"username": "dup-e2e", "password": "passw0rd-ok"}
    async with http_client(base) as c:
        r1 = await c.post("/auth/register", json=payload)
        r2 = await c.post("/auth/register", json=payload)
    assert r1.status_code == 201
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_login_wrong_password(chat_api_server) -> None:
    base = chat_api_server["base_url"]
    async with http_client(base) as c:
        await c.post("/auth/register", json={"username": "bob-e2e", "password": "correct-pw-123"})
        r = await c.post("/auth/login", json={"username": "bob-e2e", "password": "wrong-pw-456"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_without_token(chat_api_server) -> None:
    async with http_client(chat_api_server["base_url"]) as c:
        r = await c.get("/me")
    assert r.status_code in (401, 403)
