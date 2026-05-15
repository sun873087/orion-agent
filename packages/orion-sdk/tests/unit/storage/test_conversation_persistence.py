"""Conversation 整合 persistence + resume — end-to-end 測試。"""

from __future__ import annotations

import pytest

from orion_sdk.core.conversation import Conversation
from orion_sdk.core.query_loop import LoopTerminated
from orion_sdk.storage.paths import session_paths
from orion_sdk.storage.session import iter_records_sync
from tests.conftest import MockProvider, MockTurn


@pytest.mark.asyncio
async def test_conversation_writes_transcript() -> None:
    provider = MockProvider(turns=[MockTurn(text="reply")])
    conv = Conversation(
        provider=provider,  # type: ignore[arg-type]
        system_prompt="x",
        tools=[],
    )

    _ = [ev async for ev in conv.send("hello")]

    sp = session_paths(conv.session_id)
    assert sp.transcript.exists()
    records = iter_records_sync(sp.transcript)
    kinds = [r["kind"] for r in records]
    assert "session-meta" in kinds
    assert kinds.count("message") >= 2  # user + assistant
    assert "transition" in kinds


@pytest.mark.asyncio
async def test_resume_continues_conversation() -> None:
    """寫一條 conversation,resume 後 send 第二輪,state_messages 應累積完整。"""
    provider1 = MockProvider(turns=[MockTurn(text="first")])
    conv1 = Conversation(
        provider=provider1,  # type: ignore[arg-type]
        system_prompt="x",
        tools=[],
    )
    _ = [ev async for ev in conv1.send("first prompt")]
    sid = conv1.session_id
    msgs_after_first = list(conv1.state_messages)

    # resume 同 session_id,新 provider
    provider2 = MockProvider(turns=[MockTurn(text="second")])
    conv2 = await Conversation.resume(
        sid,
        provider=provider2,  # type: ignore[arg-type]
        tools=[],
    )
    assert conv2.session_id == sid
    # 重建後應有先前 messages
    assert len(conv2.state_messages) == len(msgs_after_first)
    assert conv2.state_messages[0].content == "first prompt"

    _ = [ev async for ev in conv2.send("second prompt")]
    # 含 first user/assistant + second user/assistant 至少 4 則
    assert len(conv2.state_messages) >= 4


@pytest.mark.asyncio
async def test_persistence_disabled_skips_writes() -> None:
    provider = MockProvider(turns=[MockTurn(text="x")])
    conv = Conversation(
        provider=provider,  # type: ignore[arg-type]
        system_prompt="x",
        tools=[],
        persistence_enabled=False,
    )
    _ = [ev async for ev in conv.send("hi")]
    sp = session_paths(conv.session_id)
    assert not sp.transcript.exists()


@pytest.mark.asyncio
async def test_terminate_recorded_in_transcript() -> None:
    provider = MockProvider(turns=[MockTurn(text="done")])
    conv = Conversation(
        provider=provider,  # type: ignore[arg-type]
        system_prompt="x",
        tools=[],
    )
    terminated_evs = []
    async for ev in conv.send("hi"):
        if isinstance(ev, LoopTerminated):
            terminated_evs.append(ev)
    assert len(terminated_evs) == 1

    records = iter_records_sync(session_paths(conv.session_id).transcript)
    transitions = [r for r in records if r["kind"] == "transition"]
    assert len(transitions) == 1
    assert transitions[0]["reason"] == "natural_stop"
