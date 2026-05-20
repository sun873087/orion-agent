"""token gen / hash / DB lookup / cache。"""

from __future__ import annotations

import time

import pytest

from orion_model_proxy.auth import (
    generate_token,
    hash_token,
    invalidate_cache,
    prefix_for_display,
    _cache,
    _lookup_cached_or_db,
)


def test_generate_token_format() -> None:
    t = generate_token("prod")
    assert t.startswith("sk-orion-prod-")
    # split only first 3 hyphens(random 段內可能含 `-`)
    parts = t.split("-", 3)
    assert len(parts) == 4
    # random 段 url-safe 至少 32+ char
    assert len(parts[3]) >= 32


def test_generate_token_env_validation() -> None:
    with pytest.raises(ValueError):
        generate_token("bad env!")


def test_hash_token_deterministic() -> None:
    t = "sk-orion-prod-deadbeefcafebabe"
    assert hash_token(t) == hash_token(t)
    assert hash_token(t) != hash_token(t + "x")


def test_prefix_for_display() -> None:
    t = "sk-orion-prod-9f3c8d1a2b4e5f6789abcdef01234567"
    assert prefix_for_display(t) == "sk-orion-prod-9f3c"


@pytest.mark.asyncio
async def test_db_lookup_hit_and_miss(proxy_db) -> None:
    from sqlalchemy import select
    from orion_model_proxy.db import get_session_factory
    from orion_model_proxy.models import ApiKey, User

    factory = get_session_factory()
    token = generate_token("test")
    th = hash_token(token)

    async with factory() as s:
        user = User(
            id="u1",
            email="alice@example.com",
            display_name="Alice",
            budget_usd=None,
            created_at=int(time.time()),
        )
        s.add(user)
        s.add(
            ApiKey(
                id="k1",
                user_id="u1",
                token_hash=th,
                token_prefix=prefix_for_display(token),
                label="laptop",
                created_at=int(time.time()),
            )
        )
        await s.commit()

    # hit
    async with factory() as s:
        p = await _lookup_cached_or_db(s, th)
    assert p is not None
    assert p.user_id == "u1"
    assert p.email == "alice@example.com"

    # cache 命中
    assert th in _cache

    # miss
    async with factory() as s:
        miss = await _lookup_cached_or_db(s, "deadbeef" * 8)
    assert miss is None


@pytest.mark.asyncio
async def test_revoked_key_blocked(proxy_db) -> None:
    from orion_model_proxy.db import get_session_factory
    from orion_model_proxy.models import ApiKey, User

    factory = get_session_factory()
    token = generate_token("test")
    th = hash_token(token)
    now = int(time.time())

    async with factory() as s:
        s.add(User(id="u2", email="bob@x.com", display_name=None, budget_usd=None, created_at=now))
        s.add(
            ApiKey(
                id="k2",
                user_id="u2",
                token_hash=th,
                token_prefix=prefix_for_display(token),
                label=None,
                created_at=now,
                revoked_at=now, # 已 revoked
            )
        )
        await s.commit()

    async with factory() as s:
        p = await _lookup_cached_or_db(s, th)
    assert p is None # revoked → 不認


@pytest.mark.asyncio
async def test_invalidate_cache(proxy_db) -> None:
    from orion_model_proxy.db import get_session_factory
    from orion_model_proxy.models import ApiKey, User

    factory = get_session_factory()
    token = generate_token("test")
    th = hash_token(token)
    now = int(time.time())

    async with factory() as s:
        s.add(User(id="u3", email="c@x.com", display_name=None, budget_usd=None, created_at=now))
        s.add(ApiKey(id="k3", user_id="u3", token_hash=th, token_prefix="p", label=None, created_at=now))
        await s.commit()

    async with factory() as s:
        await _lookup_cached_or_db(s, th)
    assert th in _cache

    await invalidate_cache(th)
    assert th not in _cache

    # 全 flush
    async with factory() as s:
        await _lookup_cached_or_db(s, th)
    assert th in _cache
    await invalidate_cache(None)
    assert th not in _cache
