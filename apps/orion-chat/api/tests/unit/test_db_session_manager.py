"""DbSessionManager — 用 SQLite 驗 create / get / list / delete。"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from orion_chat_api.session_manager_db import DbSessionManager
from orion_model.types import NormalizedMessage
from orion_sdk.storage.db.engine import create_db_engine, db_session, init_db
from orion_sdk.storage.db.models import User
from orion_sdk.storage.session import SessionStorage


class _DummyProvider:
    name = "anthropic"
    model = "claude-sonnet-4-6"

    async def stream(self, *args, **kwargs): # noqa: ARG002, ANN001, ANN201
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

    sid = await mgr.create(user_id=uid, conversation=_DummyConv()) # type: ignore[arg-type]
    assert sid is not None

    got = await mgr.get(uid, sid)
    assert got is not None # in cache

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
    await mgr.create(user_id=uid, conversation=_DummyConv()) # type: ignore[arg-type]
    await mgr.create(user_id=uid, conversation=_DummyConv()) # type: ignore[arg-type]
    assert await mgr.size() == 2
    await engine.dispose()


@pytest.mark.anyio
async def test_get_cache_miss_replays_messages_from_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """API 重啟後 in-memory cache 清空 — get() 應從磁碟 transcript 重建 messages,
    而不是回空白 Conversation(舊行為:待辦)。"""
    monkeypatch.setenv("ORION_SESSIONS_DIR", str(tmp_path))

    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    uid = await _new_user(engine, "alice")
    mgr = DbSessionManager(engine=engine)

    # 走 create 取得真 sid + DB row
    sid = await mgr.create(user_id=uid, conversation=_DummyConv()) # type: ignore[arg-type]

    # 模擬之前的 turn 寫過 transcript:meta + 兩則 message
    store = SessionStorage.open(sid)
    await store.record_meta(provider="anthropic", model="claude-sonnet-4-6")
    await store.record_message(NormalizedMessage(role="user", content="hi"))
    await store.record_message(NormalizedMessage(role="assistant", content="hello"))

    # 模擬重啟:清空 cache,新建一個 manager 用同一份 DB
    mgr2 = DbSessionManager(engine=engine)
    conv = await mgr2.get(uid, sid)

    assert conv is not None
    assert len(conv.state_messages) == 2
    assert conv.state_messages[0].role == "user"
    assert conv.state_messages[1].role == "assistant"
    await engine.dispose()


@pytest.mark.anyio
async def test_list_isolated_per_user() -> None:
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    uid_a = await _new_user(engine, "alice")
    uid_b = await _new_user(engine, "bob")
    mgr = DbSessionManager(engine=engine)

    await mgr.create(user_id=uid_a, conversation=_DummyConv()) # type: ignore[arg-type]
    await mgr.create(user_id=uid_a, conversation=_DummyConv()) # type: ignore[arg-type]
    await mgr.create(user_id=uid_b, conversation=_DummyConv()) # type: ignore[arg-type]

    assert len(await mgr.list_for_user(uid_a)) == 2
    assert len(await mgr.list_for_user(uid_b)) == 1
    await engine.dispose()
