"""auth_db — bcrypt + create_user / authenticate。"""

from __future__ import annotations

import pytest

from orion_agent.api.auth_db import (
    authenticate,
    create_user,
    get_user_by_username,
    hash_password,
    verify_password,
)
from orion_agent.storage.db.engine import create_db_engine, db_session, init_db


def test_hash_and_verify_roundtrip() -> None:
    h = hash_password("correct horse battery staple")
    assert h != "correct horse battery staple"
    assert verify_password("correct horse battery staple", h)
    assert not verify_password("wrong", h)


def test_hash_empty_rejected() -> None:
    with pytest.raises(ValueError):
        hash_password("")


def test_verify_against_garbage() -> None:
    assert not verify_password("x", "")
    assert not verify_password("x", "not-a-bcrypt-hash")


@pytest.mark.anyio
async def test_create_and_get() -> None:
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    async with db_session(engine) as db:
        u = await create_user(db, username="alice", password="secret123")
    assert u.username == "alice"

    async with db_session(engine) as db:
        got = await get_user_by_username(db, "alice")
    assert got is not None
    assert got.id == u.id
    await engine.dispose()


@pytest.mark.anyio
async def test_authenticate_success() -> None:
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    async with db_session(engine) as db:
        await create_user(db, username="bob", password="hunter22")

    async with db_session(engine) as db:
        u = await authenticate(db, username="bob", password="hunter22")
    assert u is not None and u.username == "bob"
    await engine.dispose()


@pytest.mark.anyio
async def test_authenticate_wrong_password() -> None:
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    async with db_session(engine) as db:
        await create_user(db, username="carol", password="abc12345")

    async with db_session(engine) as db:
        u = await authenticate(db, username="carol", password="wrong")
    assert u is None
    await engine.dispose()


@pytest.mark.anyio
async def test_authenticate_unknown_user() -> None:
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    async with db_session(engine) as db:
        u = await authenticate(db, username="ghost", password="anything")
    assert u is None
    await engine.dispose()
