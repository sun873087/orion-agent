"""DbSessionManager — 用 SQLite 驗 create / get / list / delete。"""

from __future__ import annotations

from uuid import uuid4

import pytest

from orion_agent.api.session_manager_db import DbSessionManager
from orion_agent.storage.db.engine import create_db_engine, db_session, init_db
from orion_agent.storage.db.models import User


class _DummyProvider:
    name = "anthropic"
    model = "claude-sonnet-4-6"

    async def stream(self, *args, **kwargs):  # noqa: ARG002, ANN001, ANN201
        raise NotImplementedError


class _DummyConv:
    """假 Conversation,只暴露 manager 用到的欄位。"""

    def __init__(self) -> None:
        self.provider = _DummyProvider()
        self.state_messages: list[object] = []
        self.stats = type("S", (), {"turns": 0, "input_tokens": 0, "output_tokens": 0})()


async def _new_user(engine, username: str) -> str:
    async with db_session(engine) as db:
        u = User(username=username, password_hash="x")
        db.add(u)
        await db.commit()
        await db.refresh(u)
    return u.id


@pytest.mark.anyio
async def test_create_get_delete() -> None:
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    uid = await _new_user(engine, "alice")
    mgr = DbSessionManager(engine=engine)

    sid = await mgr.create(user_id=uid, conversation=_DummyConv())  # type: ignore[arg-type]
    assert sid is not None

    got = await mgr.get(uid, sid)
    assert got is not None  # in cache

    listed = await mgr.list_for_user(uid)
    assert len(listed) == 1
    assert listed[0].session_id == sid

    deleted = await mgr.delete(uid, sid)
    assert deleted is True

    listed_after = await mgr.list_for_user(uid)
    assert listed_after == []
    await engine.dispose()


@pytest.mark.anyio
async def test_get_unknown_session() -> None:
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    uid = await _new_user(engine, "alice")
    mgr = DbSessionManager(engine=engine)

    res = await mgr.get(uid, uuid4())
    assert res is None
    await engine.dispose()


@pytest.mark.anyio
async def test_size() -> None:
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    uid = await _new_user(engine, "alice")
    mgr = DbSessionManager(engine=engine)

    assert await mgr.size() == 0
    await mgr.create(user_id=uid, conversation=_DummyConv())  # type: ignore[arg-type]
    await mgr.create(user_id=uid, conversation=_DummyConv())  # type: ignore[arg-type]
    assert await mgr.size() == 2
    await engine.dispose()


@pytest.mark.anyio
async def test_list_isolated_per_user() -> None:
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    uid_a = await _new_user(engine, "alice")
    uid_b = await _new_user(engine, "bob")
    mgr = DbSessionManager(engine=engine)

    await mgr.create(user_id=uid_a, conversation=_DummyConv())  # type: ignore[arg-type]
    await mgr.create(user_id=uid_a, conversation=_DummyConv())  # type: ignore[arg-type]
    await mgr.create(user_id=uid_b, conversation=_DummyConv())  # type: ignore[arg-type]

    assert len(await mgr.list_for_user(uid_a)) == 2
    assert len(await mgr.list_for_user(uid_b)) == 1
    await engine.dispose()
