"""storage/session.py — JSONL transcript writer。"""

from __future__ import annotations

import json
from uuid import uuid4

import anyio
import pytest

from orion_model.types import NormalizedMessage, TextBlock, ToolResultBlock
from orion_sdk.storage.replacement_state import ReplacementDecision
from orion_sdk.storage.session import SessionStorage, iter_records_sync


@pytest.mark.asyncio
async def test_record_meta_message_transition_round_trip() -> None:
    sid = uuid4()
    store = SessionStorage.open(sid)

    await store.record_meta(provider="anthropic", model="claude-sonnet-4-6", system_prompt="be brief")
    await store.record_message(NormalizedMessage(role="user", content="hello"))
    await store.record_message(
        NormalizedMessage(role="assistant", content=[TextBlock(text="hi")])
    )
    await store.record_replacement([ReplacementDecision(tool_use_id="t1", replacement="<preview>")])
    await store.record_transition(reason="natural_stop", total_turns=1)

    records = iter_records_sync(store.paths.transcript)
    assert [r["kind"] for r in records] == [
        "session-meta",
        "message",
        "message",
        "tool-result-replacement",
        "transition",
    ]
    assert records[0]["provider"] == "anthropic"
    assert records[0]["model"] == "claude-sonnet-4-6"
    assert records[1]["message"]["content"] == "hello"
    assert records[2]["message"]["content"][0]["type"] == "text"
    assert records[3]["tool_use_id"] == "t1"


@pytest.mark.asyncio
async def test_concurrent_writes_dont_interleave() -> None:
    """並發寫 50 筆訊息,每行都應 valid JSON(anyio.Lock 保護)。"""
    sid = uuid4()
    store = SessionStorage.open(sid)

    async def write_one(i: int) -> None:
        msg = NormalizedMessage(role="user", content=f"msg-{i}")
        await store.record_message(msg)

    async with anyio.create_task_group() as tg:
        for i in range(50):
            tg.start_soon(write_one, i)

    # 每行都是 valid JSON
    raw = store.paths.transcript.read_text(encoding="utf-8")
    lines = [line for line in raw.splitlines() if line.strip()]
    assert len(lines) == 50
    for line in lines:
        # 不能 raise
        parsed = json.loads(line)
        assert parsed["kind"] == "message"


@pytest.mark.asyncio
async def test_message_with_tool_result_block_serializes() -> None:
    sid = uuid4()
    store = SessionStorage.open(sid)
    msg = NormalizedMessage(
        role="user",
        content=[ToolResultBlock(tool_use_id="t1", content="foo", is_error=False)],
    )
    await store.record_message(msg)
    records = iter_records_sync(store.paths.transcript)
    assert records[0]["message"]["content"][0]["type"] == "tool_result"
    assert records[0]["message"]["content"][0]["tool_use_id"] == "t1"


def test_iter_records_skips_corrupt_lines(tmp_path) -> None:  # noqa: ANN001
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        '{"kind": "session-meta", "provider": "x", "model": "y"}\n'
        'NOT VALID JSON\n'
        '{"kind": "message", "message": {"role": "user", "content": "hi"}}\n',
        encoding="utf-8",
    )
    records = iter_records_sync(transcript)
    assert len(records) == 2
    assert records[0]["kind"] == "session-meta"
    assert records[1]["kind"] == "message"


def test_iter_records_missing_file_returns_empty(tmp_path) -> None:  # noqa: ANN001
    assert iter_records_sync(tmp_path / "absent.jsonl") == []
