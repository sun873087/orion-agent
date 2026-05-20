"""Phase X.1 — Admin REST 端到端。"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from orion_model_proxy.server import create_app


def _admin_client(admin_token: str) -> AsyncClient:
    app = create_app()
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {admin_token}"},
    )


@pytest.mark.asyncio
async def test_admin_auth_required(proxy_db, admin_token) -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/admin/users")
        assert r.status_code == 401

        r = await c.get("/admin/users", headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_create_list_delete_user(proxy_db, admin_token) -> None:
    async with _admin_client(admin_token) as c:
        # create
        r = await c.post("/admin/users", json={"email": "a@x.com", "display_name": "Alice"})
        assert r.status_code == 201, r.text
        user = r.json()
        assert user["email"] == "a@x.com"
        assert user["monthly_cost_usd"] == 0.0
        uid = user["id"]

        # duplicate email rejected
        r = await c.post("/admin/users", json={"email": "a@x.com"})
        assert r.status_code == 409

        # list
        r = await c.get("/admin/users")
        assert r.status_code == 200
        users = r.json()
        assert len(users) == 1
        assert users[0]["id"] == uid

        # delete
        r = await c.delete(f"/admin/users/{uid}")
        assert r.status_code == 204

        r = await c.get("/admin/users")
        assert r.json() == []


@pytest.mark.asyncio
async def test_key_generation_and_revoke(proxy_db, admin_token) -> None:
    async with _admin_client(admin_token) as c:
        # create user
        r = await c.post("/admin/users", json={"email": "k@x.com"})
        uid = r.json()["id"]

        # gen key
        r = await c.post(
            f"/admin/users/{uid}/keys",
            json={"label": "laptop", "env": "test"},
        )
        assert r.status_code == 201, r.text
        key = r.json()
        plaintext = key["token"]
        assert plaintext.startswith("sk-orion-test-")
        assert key["token_prefix"].startswith("sk-orion-test-")
        kid = key["id"]

        # list keys
        r = await c.get(f"/admin/users/{uid}/keys")
        assert r.status_code == 200
        keys = r.json()
        assert len(keys) == 1
        assert keys[0]["id"] == kid
        # list 不洩明文
        assert "token" not in keys[0]
        assert keys[0]["revoked_at"] is None

        # revoke
        r = await c.delete(f"/admin/keys/{kid}")
        assert r.status_code == 204

        r = await c.get(f"/admin/users/{uid}/keys")
        assert r.json()[0]["revoked_at"] is not None


@pytest.mark.asyncio
async def test_set_budget(proxy_db, admin_token) -> None:
    async with _admin_client(admin_token) as c:
        r = await c.post("/admin/users", json={"email": "b@x.com"})
        uid = r.json()["id"]

        r = await c.post(f"/admin/users/{uid}/budget", json={"budget_usd": 5.0})
        assert r.status_code == 200
        assert r.json()["budget_usd"] == 5.0

        # 解除 cap
        r = await c.post(f"/admin/users/{uid}/budget", json={"budget_usd": None})
        assert r.status_code == 200
        assert r.json()["budget_usd"] is None


@pytest.mark.asyncio
async def test_usage_rollup_empty(proxy_db, admin_token) -> None:
    """新 user 沒 usage,rollup 都是 0。"""
    async with _admin_client(admin_token) as c:
        r = await c.post("/admin/users", json={"email": "u@x.com"})
        uid = r.json()["id"]

        r = await c.get(f"/admin/users/{uid}/usage")
        assert r.status_code == 200
        data = r.json()
        assert data["user_id"] == uid
        assert data["total_cost_usd"] == 0.0
        assert data["by_model"] == {}
        assert data["request_count"] == 0


@pytest.mark.asyncio
async def test_proxy_route_auth_with_db_token(proxy_db, admin_token) -> None:
    """gen 一個 key 後,用它打 /openai/{path} 應該過 auth。

    upstream 會 503 因為沒 OPENAI_API_KEY env,但**不該** 401。
    """
    import os
    os.environ.pop("OPENAI_API_KEY", None)  # 確保 503 而非 200

    async with _admin_client(admin_token) as c:
        r = await c.post("/admin/users", json={"email": "p@x.com"})
        uid = r.json()["id"]
        r = await c.post(f"/admin/users/{uid}/keys", json={"env": "test"})
        token = r.json()["token"]

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # 沒帶 token → 401
        r = await c.get("/openai/v1/models")
        assert r.status_code == 401

        # 帶錯 token → 403
        r = await c.get(
            "/openai/v1/models",
            headers={"Authorization": "Bearer sk-orion-prod-deadbeefdeadbeefdeadbeefdeadbeef"},
        )
        assert r.status_code == 403

        # 帶對 token → auth 過,撞 upstream 沒 key(503)
        r = await c.get("/openai/v1/models", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 503
        assert "OPENAI_API_KEY" in r.text
