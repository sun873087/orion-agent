"""storage/resume.py — 從 transcript 重建 session snapshot。"""

from __future__ import annotations

from uuid import uuid4

import pytest

from orion_agent.llm.types import (
    NormalizedMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from orion_agent.storage.replacement_state import ReplacementDecision
from orion_agent.storage.resume import load_session
from orion_agent.storage.session import SessionStorage


@pytest.mark.asyncio
async def test_resume_round_trip_basic() -> None:
    sid = uuid4()
    store = SessionStorage.open(sid)
    await store.record_meta(provider="anthropic", model="claude-sonnet-4-6", system_prompt="sp")
    await store.record_message(NormalizedMessage(role="user", content="hi"))
    await store.record_message(
        NormalizedMessage(role="assistant", content=[TextBlock(text="hello back")])
    )
    await store.record_transition(reason="natural_stop", total_turns=1)

    snap = load_session(sid)
    assert snap.session_id == sid
    assert snap.system_prompt == "sp"
    assert snap.provider == "anthropic"
    assert snap.model == "claude-sonnet-4-6"
    assert len(snap.messages) == 2
    assert snap.messages[0].role == "user"
    assert snap.messages[0].content == "hi"
    assert snap.messages[1].role == "assistant"
    assert isinstance(snap.messages[1].content, list)
    assert snap.messages[1].content[0].text == "hello back"  # type: ignore[union-attr]
    assert len(snap.transitions) == 1


@pytest.mark.asyncio
async def test_resume_reconstructs_replacement_state() -> None:
    sid = uuid4()
    store = SessionStorage.open(sid)
    await store.record_meta(provider="anthropic", model="x")
    # tool_use → tool_result(2 個 ID,1 個曾被替換)
    await store.record_message(
        NormalizedMessage(
            role="assistant",
            content=[
                ToolUseBlock(id="t1", name="Read", input={}),
                ToolUseBlock(id="t2", name="Read", input={}),
            ],
        )
    )
    await store.record_message(
        NormalizedMessage(
            role="user",
            content=[
                ToolResultBlock(tool_use_id="t1", content="small"),
                ToolResultBlock(tool_use_id="t2", content="<persisted-output ...>"),
            ],
        )
    )
    await store.record_replacement([
        ReplacementDecision(tool_use_id="t2", replacement="<persisted-output ...>"),
    ])

    snap = load_session(sid)
    assert "t1" in snap.replacement_state.seen_ids
    assert "t2" in snap.replacement_state.seen_ids
    assert snap.replacement_state.is_frozen("t1")
    assert snap.replacement_state.is_must_reapply("t2")
    assert snap.replacement_state.replacements["t2"] == "<persisted-output ...>"


@pytest.mark.asyncio
async def test_resume_handles_missing_transcript() -> None:
    """Session 沒寫過任何東西 → 回空 snapshot,不 raise。"""
    sid = uuid4()
    snap = load_session(sid)
    assert snap.messages == []
    assert snap.replacement_state.seen_ids == set()
