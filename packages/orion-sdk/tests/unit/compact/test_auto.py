"""compact/auto.py — autoCompact threshold + 觸發。"""

from __future__ import annotations

import pytest

from orion_sdk.compact.auto import (
    AUTO_COMPACT_THRESHOLD_DEFAULT,
    auto_compact_if_needed,
    estimate_token_count,
)
from orion_sdk.compact.strategies import TruncateStrategy
from orion_model.types import (
    NormalizedMessage,
    TextBlock,
    TombstoneBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from tests.conftest import MockProvider


def test_threshold_default() -> None:
    assert AUTO_COMPACT_THRESHOLD_DEFAULT == 0.8


def test_estimate_token_count_str_content() -> None:
    msgs = [NormalizedMessage(role="user", content="abcd" * 25)]  # 100 chars
    assert estimate_token_count(msgs) == 25


def test_estimate_token_count_with_blocks() -> None:
    msgs = [NormalizedMessage(
        role="assistant",
        content=[TextBlock(text="x" * 200), ToolUseBlock(id="t", name="X", input={})],
    )]
    # ~200/4 = 50 + tool name "X" + str({})="{}",粗略 50+
    assert estimate_token_count(msgs) > 40


@pytest.mark.asyncio
async def test_no_compact_when_under_threshold() -> None:
    msgs = [NormalizedMessage(role="user", content="hi"), NormalizedMessage(role="assistant", content="hello")]
    provider = MockProvider()
    out, was = await auto_compact_if_needed(msgs, provider=provider)  # type: ignore[arg-type]
    assert was is False
    assert out == msgs


@pytest.mark.asyncio
async def test_no_compact_when_few_messages() -> None:
    """< 4 messages 即使爆 budget 也不 compact(沒意義)。"""
    big_text = "x" * 1_000_000
    msgs = [NormalizedMessage(role="user", content=big_text)]
    provider = MockProvider()
    out, was = await auto_compact_if_needed(msgs, provider=provider)  # type: ignore[arg-type]
    assert was is False


@pytest.mark.asyncio
async def test_compact_triggers_above_threshold(monkeypatch) -> None:  # noqa: ANN001
    """強制低 threshold + 多 messages → 應觸發。"""
    monkeypatch.setenv("ORION_AUTO_COMPACT_THRESHOLD", "0.1")
    # 製造一堆 messages,token 估算超 200K * 0.1 = 20K 上限
    msgs: list[NormalizedMessage] = []
    for i in range(20):
        msgs.append(NormalizedMessage(role="user", content="a" * 5000))
        msgs.append(NormalizedMessage(role="assistant", content=f"reply {i}"))

    provider = MockProvider()
    out, was = await auto_compact_if_needed(
        msgs, provider=provider,  # type: ignore[arg-type]
        strategy=TruncateStrategy(),  # 用 TruncateStrategy 避免要 mock LLM 回應
    )
    assert was is True
    # 第一則應是 TombstoneBlock
    assert isinstance(out[0].content, list)
    assert isinstance(out[0].content[0], TombstoneBlock)
    # 後面 messages 至少剩一些
    assert len(out) < len(msgs)


@pytest.mark.asyncio
async def test_cutoff_safe_boundary_keeps_tool_pair_together(monkeypatch) -> None:  # noqa: ANN001
    """cutoff 落在 assistant tool_use 與接著的 user tool_result 中間 → 推後一格。"""
    monkeypatch.setenv("ORION_AUTO_COMPACT_THRESHOLD", "0.1")
    # 用很大的 message content 讓 4 訊息超過 200_000 * 0.1 = 20_000 tokens
    big = "x" * 80_000  # 80K chars ≈ 20K tokens 一條訊息
    msgs: list[NormalizedMessage] = []
    msgs.append(NormalizedMessage(role="user", content=big))
    msgs.append(
        NormalizedMessage(
            role="assistant",
            content=[ToolUseBlock(id="t1", name="Read", input={})],
        )
    )
    msgs.append(
        NormalizedMessage(
            role="user",
            content=[ToolResultBlock(tool_use_id="t1", content=big)],
        )
    )
    msgs.append(NormalizedMessage(role="assistant", content="ok"))

    provider = MockProvider()
    out, was = await auto_compact_if_needed(
        msgs, provider=provider,  # type: ignore[arg-type]
        strategy=TruncateStrategy(),
    )
    assert was is True
    # 第一則 tombstone 應該包含原 0-2(含 tool pair),不切到中間
    assert isinstance(out[0].content, list)
    assert isinstance(out[0].content[0], TombstoneBlock)
    tombstone = out[0].content[0]
    # range 應該到 index >= 2(把 tool_result 一起壓掉)
    assert tombstone.range_end_msg_index >= 2
