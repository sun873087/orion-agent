"""SQLAlchemy models — 用 in-memory SQLite 跑 create_all + CRUD。"""

from __future__ import annotations

from uuid import uuid4

import pytest

from orion_agent.storage.db.engine import create_db_engine, db_session, init_db
from orion_agent.storage.db.models import Message, Session, User


@pytest.mark.anyio
async def test_create_user_and_query() -> None:
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    async with db_session(engine) as db:
        u = User(username="alice", password_hash="x")
        db.add(u)
        await db.commit()
        await db.refresh(u)
    assert u.id  # UUID auto-assigned
    assert u.username == "alice"
    await engine.dispose()


@pytest.mark.anyio
async def test_session_message_relationship() -> None:
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    async with db_session(engine) as db:
        u = User(username="bob", password_hash="x")
        db.add(u)
        await db.commit()
        await db.refresh(u)

        s = Session(
            id=str(uuid4()),
            user_id=u.id,
            provider="anthropic",
            model="claude-sonnet-4-6",
        )
        db.add(s)
        await db.commit()
        await db.refresh(s)

        m = Message(
            id=str(uuid4()),
            session_id=s.id,
            role="user",
            content_json=[{"type": "text", "text": "hi"}],
            raw_text="hi",
        )
        db.add(m)
        await db.commit()
    assert s.id and m.session_id == s.id
    await engine.dispose()


@pytest.mark.anyio
async def test_unique_username() -> None:
    from sqlalchemy.exc import IntegrityError

    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    async with db_session(engine) as db:
        db.add(User(username="dup", password_hash="x"))
        await db.commit()

    async with db_session(engine) as db:
        db.add(User(username="dup", password_hash="x"))
        with pytest.raises(IntegrityError):
            await db.commit()
    await engine.dispose()
