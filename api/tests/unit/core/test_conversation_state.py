"""Conversation 跨 send() 累積 messages、stats。"""

from __future__ import annotations

import pytest

from orion_agent.core.conversation import Conversation
from tests.conftest import MockProvider, MockTurn


@pytest.mark.asyncio
async def test_two_sends_accumulate_messages() -> None:
    provider = MockProvider(turns=[
        MockTurn(text="hi back"),
        MockTurn(text="and again"),
    ])
    conv = Conversation(
        provider=provider,  # type: ignore[arg-type]
        system_prompt="x",
        tools=[],
    )

    _ = [ev async for ev in conv.send("hello")]
    assert len(conv.state_messages) == 2  # user + assistant

    _ = [ev async for ev in conv.send("hi again")]
    assert len(conv.state_messages) == 4  # +user +assistant


@pytest.mark.asyncio
async def test_stats_track_turns() -> None:
    provider = MockProvider(turns=[MockTurn(text="reply")])
    conv = Conversation(
        provider=provider,  # type: ignore[arg-type]
        system_prompt="x",
        tools=[],
    )

    _ = [ev async for ev in conv.send("hi")]
    assert conv.stats.turns == 1
    assert conv.stats.tool_calls == 0
    assert conv.stats.tool_errors == 0


@pytest.mark.asyncio
async def test_state_messages_replaced_with_loop_final() -> None:
    """LoopTerminated 帶回的 final_messages 會替換 conv.state_messages。"""
    provider = MockProvider(turns=[MockTurn(text="reply")])
    conv = Conversation(
        provider=provider,  # type: ignore[arg-type]
        system_prompt="x",
        tools=[],
    )
    _ = [ev async for ev in conv.send("hi")]
    # 最後 state_messages 含 user + assistant 兩則
    assert conv.state_messages[0].role == "user"
    assert conv.state_messages[1].role == "assistant"
