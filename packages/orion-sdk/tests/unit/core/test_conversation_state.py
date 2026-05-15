"""Conversation 跨 send() 累積 messages、stats。"""

from __future__ import annotations

import pytest

from orion_sdk.core.conversation import (
    _DEFAULT_MAX_TOKENS_PER_TURN,
    Conversation,
    _default_max_tokens_per_turn,
    pick_max_tokens_per_turn,
)
from orion_sdk._testing import MockProvider, MockTurn


def test_default_max_tokens_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ORION_MAX_TOKENS_PER_TURN", raising=False)
    assert _default_max_tokens_per_turn() == _DEFAULT_MAX_TOKENS_PER_TURN


def test_default_max_tokens_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORION_MAX_TOKENS_PER_TURN", "32768")
    assert _default_max_tokens_per_turn() == 32768


def test_default_max_tokens_invalid_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORION_MAX_TOKENS_PER_TURN", "garbage")
    assert _default_max_tokens_per_turn() == _DEFAULT_MAX_TOKENS_PER_TURN
    monkeypatch.setenv("ORION_MAX_TOKENS_PER_TURN", "0")
    assert _default_max_tokens_per_turn() == _DEFAULT_MAX_TOKENS_PER_TURN


def test_pick_max_tokens_uses_catalog_when_no_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ORION_MAX_TOKENS_PER_TURN", raising=False)
    # claude-sonnet-4-6 在內建 catalog 是 64000
    assert pick_max_tokens_per_turn("anthropic", "claude-sonnet-4-6") == 64000
    # haiku 是 8192
    assert pick_max_tokens_per_turn("anthropic", "claude-haiku-4-5") == 8192


def test_pick_max_tokens_caps_env_at_model_max(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORION_MAX_TOKENS_PER_TURN", "100000")
    # haiku 上限 8192,env 100000 → cap 至 8192,避免 API 422
    assert pick_max_tokens_per_turn("anthropic", "claude-haiku-4-5") == 8192


def test_pick_max_tokens_unknown_model_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ORION_MAX_TOKENS_PER_TURN", raising=False)
    # catalog 不認識 → 16384 default
    assert pick_max_tokens_per_turn("anthropic", "claude-future-99") == _DEFAULT_MAX_TOKENS_PER_TURN


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
