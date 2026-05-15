"""compact/strategies.py — Sonnet summary + Truncate fallback。"""

from __future__ import annotations

import pytest

from orion_sdk.compact.strategies import (
    SonnetSummaryStrategy,
    TruncateStrategy,
)
from orion_model.types import (
    NormalizedMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from tests.conftest import MockProvider, MockTurn


@pytest.mark.asyncio
async def test_truncate_strategy() -> None:
    msgs = [
        NormalizedMessage(role="user", content="a"),
        NormalizedMessage(role="assistant", content="b"),
        NormalizedMessage(role="user", content="c"),
    ]
    out = await TruncateStrategy().summarize(msgs, provider=MockProvider())  # type: ignore[arg-type]
    assert "3 messages" in out
    assert "user" in out


@pytest.mark.asyncio
async def test_truncate_empty() -> None:
    out = await TruncateStrategy().summarize([], provider=MockProvider())  # type: ignore[arg-type]
    assert "no prior" in out.lower()


@pytest.mark.asyncio
async def test_sonnet_summary_uses_provider() -> None:
    """SonnetSummaryStrategy 會 call provider 並用回傳 text。"""
    provider = MockProvider(turns=[MockTurn(text="A succinct summary of stuff.")])
    msgs = [
        NormalizedMessage(role="user", content="hi"),
        NormalizedMessage(role="assistant", content=[TextBlock(text="hello")]),
        NormalizedMessage(
            role="assistant",
            content=[ToolUseBlock(id="t", name="Read", input={"path": "/etc"})],
        ),
        NormalizedMessage(
            role="user",
            content=[ToolResultBlock(tool_use_id="t", content="contents")],
        ),
    ]
    out = await SonnetSummaryStrategy().summarize(msgs, provider=provider)  # type: ignore[arg-type]
    assert "succinct summary" in out


@pytest.mark.asyncio
async def test_sonnet_summary_empty_response_falls_back() -> None:
    """LLM 回空 → fallback truncate。"""
    provider = MockProvider(turns=[MockTurn(text="")])
    msgs = [NormalizedMessage(role="user", content="x")]
    out = await SonnetSummaryStrategy().summarize(msgs, provider=provider)  # type: ignore[arg-type]
    # truncate fallback 會印 "1 messages"
    assert "1 messages" in out or "elided" in out
