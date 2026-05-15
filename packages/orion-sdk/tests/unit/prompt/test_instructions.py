"""Custom instructions(Web chat 模式)。Phase 13。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from orion_sdk.prompt.instructions import (
    USER_INSTRUCTION_LIMIT_CHARS,
    CustomInstructions,
    assemble_instructions_section,
    get_custom_instructions,
    upsert_conversation_instructions,
    upsert_user_instructions,
)
from orion_sdk.storage.db.engine import (
    create_db_engine,
    db_session,
    init_db,
)
from orion_sdk.storage.db.models import Session as SessionModel
from orion_sdk.storage.db.models import User


@pytest_asyncio.fixture
async def db() -> AsyncIterator[AsyncSession]:
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    async with db_session(engine) as session:
        # 建一個 user 與 session 供 FK 用
        u = User(id="u1", username="alice", password_hash="x")
        session.add(u)
        s = SessionModel(id="sid-1", user_id="u1")
        session.add(s)
        await session.commit()
        yield session
    await engine.dispose()


def test_assemble_empty() -> None:
    inst = CustomInstructions(user_level=None, conversation_level=None)
    assert assemble_instructions_section(inst) == ""


def test_assemble_user_only() -> None:
    inst = CustomInstructions(user_level="I prefer Python.", conversation_level=None)
    out = assemble_instructions_section(inst)
    assert "About this user" in out
    assert "Python" in out
    assert "Context for this conversation" not in out


def test_assemble_both_levels() -> None:
    inst = CustomInstructions(
        user_level="terse",
        conversation_level="this chat is about ML",
    )
    out = assemble_instructions_section(inst)
    assert "About this user" in out
    assert "Context for this conversation" in out


@pytest.mark.asyncio
async def test_get_returns_none_when_empty(db: AsyncSession) -> None:
    inst = await get_custom_instructions(user_id="u1", session_id="sid-1", db=db)
    assert inst.user_level is None
    assert inst.conversation_level is None
    assert inst.is_empty()


@pytest.mark.asyncio
async def test_upsert_then_get_user(db: AsyncSession) -> None:
    await upsert_user_instructions(
        user_id="u1", instructions="be concise", db=db,
    )
    inst = await get_custom_instructions(user_id="u1", session_id=None, db=db)
    assert inst.user_level == "be concise"


@pytest.mark.asyncio
async def test_upsert_then_get_conversation(db: AsyncSession) -> None:
    await upsert_conversation_instructions(
        session_id="sid-1", instructions="this is a code review", db=db,
    )
    inst = await get_custom_instructions(
        user_id="u1", session_id="sid-1", db=db,
    )
    assert inst.conversation_level == "this is a code review"


@pytest.mark.asyncio
async def test_upsert_clears_with_empty(db: AsyncSession) -> None:
    await upsert_user_instructions(user_id="u1", instructions="set", db=db)
    await upsert_user_instructions(user_id="u1", instructions="", db=db)
    inst = await get_custom_instructions(user_id="u1", session_id=None, db=db)
    assert inst.user_level is None


@pytest.mark.asyncio
async def test_truncates_to_limit(db: AsyncSession) -> None:
    big = "x" * (USER_INSTRUCTION_LIMIT_CHARS + 100)
    await upsert_user_instructions(user_id="u1", instructions=big, db=db)
    inst = await get_custom_instructions(user_id="u1", session_id=None, db=db)
    assert inst.user_level is not None
    assert len(inst.user_level) <= USER_INSTRUCTION_LIMIT_CHARS + 50  # +suffix
    assert inst.user_level.endswith("...[truncated]")


@pytest.mark.asyncio
async def test_upsert_idempotent_update(db: AsyncSession) -> None:
    await upsert_user_instructions(user_id="u1", instructions="v1", db=db)
    await upsert_user_instructions(user_id="u1", instructions="v2", db=db)
    inst = await get_custom_instructions(user_id="u1", session_id=None, db=db)
    assert inst.user_level == "v2"
