"""Phase X.4 — Admin Web UI smoke tests。

不測 HTML 排版,只測:auth、redirect、login flow、key 生成 + 在 detail 頁顯示。
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from orion_model_proxy.server import create_app


@pytest.mark.asyncio
async def test_login_page_renders(proxy_db) -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/admin/ui/")
        assert r.status_code == 200
        assert "Admin token" in r.text


@pytest.mark.asyncio
async def test_login_with_bad_token_returns_to_login(proxy_db) -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/admin/ui/login", data={"token": "wrong"}, follow_redirects=False)
        assert r.status_code == 303
        assert "/admin/ui/?err=invalid" in r.headers["location"]


@pytest.mark.asyncio
async def test_login_with_correct_token_sets_cookie(proxy_db, admin_token) -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/admin/ui/login", data={"token": admin_token}, follow_redirects=False
        )
        assert r.status_code == 303
        assert r.headers["location"].endswith("/admin/ui/users")
        # cookie 有設
        assert "orion_admin" in r.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_users_page_requires_auth(proxy_db) -> None:
    """沒 cookie → 不能進 users 頁。"""
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/admin/ui/users", follow_redirects=False)
        # FastAPI HTTPException 303 → 303 redirect
        assert r.status_code == 303


@pytest.mark.asyncio
async def test_full_flow_create_user_gen_key(proxy_db, admin_token) -> None:
    """login → 建 user → gen key → detail 頁含明文 token。"""
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # login
        await c.post("/admin/ui/login", data={"token": admin_token})
        # cookie 已自動帶

        # create user
        r = await c.post(
            "/admin/ui/users",
            data={"email": "uitest@x.com", "display_name": "UI Test", "budget_usd": "5"},
            follow_redirects=True,
        )
        assert r.status_code == 200
        assert "uitest@x.com" in r.text

        # users list 看到
        r = await c.get("/admin/ui/users")
        assert "uitest@x.com" in r.text
        assert "$5.0000" in r.text  # budget shown

        # 從 users list 找到 user id(粗暴 regex,但能 work)
        import re

        m = re.search(r"/admin/ui/users/([a-f0-9]{32})", r.text)
        assert m is not None
        uid = m.group(1)

        # gen key
        r = await c.post(
            f"/admin/ui/users/{uid}/keys",
            data={"label": "test-key", "env": "dev"},
            follow_redirects=True,
        )
        assert r.status_code == 200
        assert "sk-orion-dev-" in r.text  # 明文 token 在 flash 區
        assert "test-key" in r.text  # label 顯示在 keys table

        # set budget(remove cap)
        r = await c.post(
            f"/admin/ui/users/{uid}/budget",
            data={"budget_usd": ""},
            follow_redirects=True,
        )
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_logout_clears_cookie(proxy_db, admin_token) -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/admin/ui/login", data={"token": admin_token})
        # 有 cookie 能進
        r = await c.get("/admin/ui/users")
        assert r.status_code == 200
        # logout
        r = await c.post("/admin/ui/logout", follow_redirects=False)
        assert r.status_code == 303
        # cookie 被清
        cookie_header = r.headers.get("set-cookie", "")
        assert "orion_admin=" in cookie_header
        # 再進就被擋
        r2 = await c.get("/admin/ui/users", follow_redirects=False)
        assert r2.status_code == 303
