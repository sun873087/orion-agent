"""storage/resume.py — 從 transcript 重建 session snapshot。"""

from __future__ import annotations

from uuid import uuid4

import pytest

from orion_model.types import (
    NormalizedMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from orion_sdk.storage.replacement_state import ReplacementDecision
from orion_sdk.storage.resume import load_session
from orion_sdk.storage.session import SessionStorage


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


# ─── validate_and_repair_messages tests ───────────────────────────────────


def test_validate_no_dangling_returns_unchanged() -> None:
    from orion_sdk.storage.resume import validate_and_repair_messages

    msgs = [
        NormalizedMessage(
            role="assistant",
            content=[ToolUseBlock(id="t1", name="Read", input={})],
        ),
        NormalizedMessage(
            role="user",
            content=[ToolResultBlock(tool_use_id="t1", content="ok")],
        ),
    ]
    repaired, warnings = validate_and_repair_messages(msgs)
    assert warnings == []
    assert len(repaired) == 2


def test_validate_dangling_at_end_appends_synthetic() -> None:
    """assistant emit tool_use 後 transcript 結束 → 追一則 synthetic user。"""
    from orion_sdk.storage.resume import validate_and_repair_messages

    msgs = [
        NormalizedMessage(role="user", content="run something"),
        NormalizedMessage(
            role="assistant",
            content=[ToolUseBlock(id="t1", name="Bash", input={})],
        ),
        # ← 中途 kill,沒 tool_result
    ]
    repaired, warnings = validate_and_repair_messages(msgs)
    assert len(warnings) == 1
    assert "t1" in warnings[0]
    assert len(repaired) == 3
    # 第三則應是 synthetic user with tool_result(is_error=True)
    last = repaired[2]
    assert last.role == "user"
    assert isinstance(last.content, list)
    assert isinstance(last.content[0], ToolResultBlock)
    assert last.content[0].tool_use_id == "t1"
    assert last.content[0].is_error is True
    assert "did not complete" in str(last.content[0].content).lower()


def test_validate_dangling_in_middle() -> None:
    """中間 assistant 有 tool_use 但 user 沒對應 result → 也插 synthetic。"""
    from orion_sdk.storage.resume import validate_and_repair_messages

    msgs = [
        NormalizedMessage(
            role="assistant",
            content=[ToolUseBlock(id="bad", name="X", input={})],
        ),
        NormalizedMessage(role="user", content="continue"),  # 不是 tool_result
        NormalizedMessage(role="assistant", content=[TextBlock(text="ok")]),
    ]
    repaired, warnings = validate_and_repair_messages(msgs)
    assert len(warnings) == 1
    # 應在 idx 0 後插 synthetic
    assert len(repaired) == 4
    assert repaired[0].role == "assistant"
    assert repaired[1].role == "user"
    assert isinstance(repaired[1].content, list)
    assert isinstance(repaired[1].content[0], ToolResultBlock)
    # 後續訊息保持
    assert repaired[2].content == "continue"


def test_validate_multiple_dangling_in_one_assistant() -> None:
    """一個 assistant 有兩個 tool_use 都 dangling → 一則 synthetic 內含兩個 tool_result。"""
    from orion_sdk.storage.resume import validate_and_repair_messages

    msgs = [
        NormalizedMessage(
            role="assistant",
            content=[
                ToolUseBlock(id="a", name="Glob", input={}),
                ToolUseBlock(id="b", name="Grep", input={}),
            ],
        ),
    ]
    repaired, warnings = validate_and_repair_messages(msgs)
    assert len(warnings) == 2
    assert len(repaired) == 2
    synthetic = repaired[1]
    assert isinstance(synthetic.content, list)
    assert len(synthetic.content) == 2
    ids = {b.tool_use_id for b in synthetic.content if isinstance(b, ToolResultBlock)}
    assert ids == {"a", "b"}


@pytest.mark.asyncio
async def test_load_session_repairs_dangling_transcript() -> None:
    """End-to-end:寫一條中途 kill 的 transcript,load_session 自動修。"""
    sid = uuid4()
    store = SessionStorage.open(sid)
    await store.record_meta(provider="anthropic", model="x")
    await store.record_message(NormalizedMessage(role="user", content="please run"))
    await store.record_message(
        NormalizedMessage(
            role="assistant",
            content=[ToolUseBlock(id="killed", name="Bash", input={"command": "x"})],
        )
    )
    # 沒寫 user 的 tool_result(模擬 process kill)

    snap = load_session(sid)
    assert len(snap.warnings) == 1
    assert "killed" in snap.warnings[0]
    # messages 應已 repaired:user → assistant(tool_use) → synthetic user(tool_result error)
    assert len(snap.messages) == 3
    last = snap.messages[2]
    assert last.role == "user"
    assert isinstance(last.content, list)
    assert isinstance(last.content[0], ToolResultBlock)
    assert last.content[0].is_error is True
