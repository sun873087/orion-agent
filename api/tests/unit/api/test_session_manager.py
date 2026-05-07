"""api/session_manager.py。"""

from __future__ import annotations

from uuid import uuid4

import pytest

from orion_agent.api.session_manager import SessionManager
from orion_agent.core.conversation import Conversation
from tests.conftest import MockProvider


def _make_conv() -> Conversation:
    return Conversation(provider=MockProvider(), persistence_enabled=False)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_create_and_get() -> None:
    sm = SessionManager()
    conv = _make_conv()
    sid = await sm.create(user_id="alice", conversation=conv)
    fetched = await sm.get("alice", sid)
    assert fetched is conv


@pytest.mark.asyncio
async def test_get_other_user_returns_none() -> None:
    sm = SessionManager()
    conv = _make_conv()
    sid = await sm.create(user_id="alice", conversation=conv)
    fetched = await sm.get("bob", sid)
    assert fetched is None


@pytest.mark.asyncio
async def test_create_with_explicit_session_id() -> None:
    sm = SessionManager()
    conv = _make_conv()
    sid = uuid4()
    returned = await sm.create(user_id="alice", session_id=sid, conversation=conv)
    assert returned == sid


@pytest.mark.asyncio
async def test_delete() -> None:
    sm = SessionManager()
    conv = _make_conv()
    sid = await sm.create(user_id="alice", conversation=conv)
    assert await sm.delete("alice", sid) is True
    assert await sm.delete("alice", sid) is False  # already gone
    assert await sm.get("alice", sid) is None


@pytest.mark.asyncio
async def test_list_for_user() -> None:
    sm = SessionManager()
    await sm.create(user_id="alice", conversation=_make_conv())
    await sm.create(user_id="alice", conversation=_make_conv())
    await sm.create(user_id="bob", conversation=_make_conv())

    alice_sessions = await sm.list_for_user("alice")
    assert len(alice_sessions) == 2

    bob_sessions = await sm.list_for_user("bob")
    assert len(bob_sessions) == 1


@pytest.mark.asyncio
async def test_size() -> None:
    sm = SessionManager()
    assert await sm.size() == 0
    await sm.create(user_id="alice", conversation=_make_conv())
    assert await sm.size() == 1
