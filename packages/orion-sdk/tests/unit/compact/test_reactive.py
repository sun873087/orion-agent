"""compact/reactive.py — prompt-too-long detection + force compact。"""

from __future__ import annotations

import pytest

from orion_sdk.compact.reactive import (
    is_prompt_too_long_error,
    reactive_compact,
)
from orion_model.types import (
    NormalizedMessage,
    TombstoneBlock,
)
from orion_sdk._testing import MockProvider, MockTurn


def test_detect_anthropic_prompt_too_long() -> None:
    e = Exception("Error: prompt is too long: 250000 tokens > 200000 limit")
    assert is_prompt_too_long_error(e) is True


def test_detect_openai_context_length() -> None:
    e = Exception("OpenAI error: context_length_exceeded for input")
    assert is_prompt_too_long_error(e) is True


def test_detect_string_above_max() -> None:
    e = Exception("string_above_max_length")
    assert is_prompt_too_long_error(e) is True


def test_unrelated_error_not_detected() -> None:
    e = Exception("some other error")
    assert is_prompt_too_long_error(e) is False


@pytest.mark.asyncio
async def test_reactive_compact_creates_tombstone() -> None:
    msgs = [
        NormalizedMessage(role="user", content=f"message {i}") for i in range(10)
    ]
    provider = MockProvider(turns=[MockTurn(text="forced summary")])
    out = await reactive_compact(msgs, provider=provider)  # type: ignore[arg-type]
    # 應壓縮過,第一則 TombstoneBlock
    assert isinstance(out[0].content, list)
    assert isinstance(out[0].content[0], TombstoneBlock)
    # 比原 messages 短
    assert len(out) < len(msgs)


@pytest.mark.asyncio
async def test_reactive_compact_few_messages_unchanged() -> None:
    msgs = [NormalizedMessage(role="user", content="x")]
    provider = MockProvider()
    out = await reactive_compact(msgs, provider=provider)  # type: ignore[arg-type]
    # < 4 訊息不壓
    assert out == msgs
