"""Phase 33-C — proxy DB backup / restore 跨 schema round-trip。"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest
from sqlalchemy import select

from orion_model_proxy.backup import backup_to_zip, restore_from_zip
from orion_model_proxy.db import get_session_factory
from orion_model_proxy.models import ApiKey, AuditLog, UsageLog, User


@pytest.mark.asyncio
async def test_backup_restore_round_trip(proxy_db) -> None:
    """塞料 → backup → wipe → restore → 內容一致。"""
    factory = get_session_factory()
    now = int(time.time())
    async with factory() as s:
        s.add(User(id="u1", email="a@x.com", display_name="Alice",
                   budget_usd=10.0, created_at=now))
        s.add(ApiKey(
            id="k1", user_id="u1", token_hash="hash1",
            token_prefix="sk-orion-prod-aaaa",
            label="laptop", created_at=now,
        ))
        s.add(UsageLog(
            user_id="u1", api_key_id="k1",
            provider="openai", model="gpt-5",
            endpoint="/openai/v1/chat/completions",
            input_tokens=100, output_tokens=50,
            cache_read_tokens=0, cache_creation_tokens=None,
            cost_usd=0.001, ts=now,
            client_id="orion-cli", request_id="r1",
        ))
        s.add(AuditLog(
            ts=now, action="user.create",
            target_type="user", target_id="u1", detail='{"email":"a@x.com"}',
        ))
        await s.commit()

    with tempfile.TemporaryDirectory(prefix="proxy-backup-") as d:
        zip_path = Path(d) / "backup.zip"

        # Backup
        async with factory() as s:
            stats = await backup_to_zip(s, zip_path)
        assert stats.table_counts["users"] == 1
        assert stats.table_counts["api_keys"] == 1
        assert stats.table_counts["usage_log"] == 1
        assert stats.table_counts["audit_log"] == 1
        assert zip_path.exists()
        assert zip_path.stat().st_size > 0

        # 摧毀 DB — wipe everything
        async with factory() as s:
            from sqlalchemy import delete
            await s.execute(delete(UsageLog))
            await s.execute(delete(ApiKey))
            await s.execute(delete(User))
            await s.execute(delete(AuditLog))
            await s.commit()

        async with factory() as s:
            users = (await s.execute(select(User))).scalars().all()
            assert users == []

        # Restore
        async with factory() as s:
            restore_stats = await restore_from_zip(s, zip_path)
        assert restore_stats.schema_version == 1
        assert restore_stats.table_counts["users"] == 1

        # 驗證內容
        async with factory() as s:
            users = (await s.execute(select(User))).scalars().all()
            assert len(users) == 1
            u = users[0]
            assert u.email == "a@x.com"
            assert u.budget_usd == 10.0

            keys = (await s.execute(select(ApiKey))).scalars().all()
            assert len(keys) == 1
            k = keys[0]
            assert k.token_hash == "hash1"
            assert k.token_prefix == "sk-orion-prod-aaaa"
            assert k.user_id == "u1"

            usage = (await s.execute(select(UsageLog))).scalars().all()
            assert len(usage) == 1
            ul = usage[0]
            assert ul.client_id == "orion-cli"
            assert ul.cost_usd == 0.001


@pytest.mark.asyncio
async def test_restore_rejects_bad_zip(proxy_db) -> None:
    factory = get_session_factory()
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
        f.write(b"not a zip")
        path = Path(f.name)
    try:
        async with factory() as s:
            with pytest.raises(Exception):  # zipfile.BadZipFile or ValueError
                await restore_from_zip(s, path)
    finally:
        path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_backup_restore_via_admin_api(proxy_db, admin_token) -> None:
    """e2e:admin POST /backup → /restore。"""
    from httpx import ASGITransport, AsyncClient
    from orion_model_proxy.server import create_app

    factory = get_session_factory()
    async with factory() as s:
        s.add(User(id="api-u", email="api@x.com", display_name=None,
                   budget_usd=None, created_at=int(time.time())))
        await s.commit()

    app = create_app()
    headers = {"Authorization": f"Bearer {admin_token}"}
    with tempfile.TemporaryDirectory(prefix="proxy-backup-api-") as d:
        zip_path = Path(d) / "via-api.zip"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t", headers=headers) as c:
            r = await c.post(f"/admin/maintenance/backup?target_path={zip_path}")
            assert r.status_code == 200, r.text
            assert r.json()["table_counts"]["users"] == 1

            # 摧毀
            from sqlalchemy import delete
            async with factory() as s:
                await s.execute(delete(User))
                await s.commit()

            r = await c.post(f"/admin/maintenance/restore?source_path={zip_path}")
            assert r.status_code == 200, r.text

            async with factory() as s:
                users = (await s.execute(select(User))).scalars().all()
            assert any(u.email == "api@x.com" for u in users)
