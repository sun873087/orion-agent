"""AgentSummary — Phase 15。"""

from __future__ import annotations

import pytest

from orion_model.types import (
    NormalizedMessage,
    TextBlock,
    ToolUseBlock,
)
from orion_sdk.multi_agent.agent_summary import generate_agent_summary
from tests.conftest import MockProvider, MockTurn


@pytest.mark.asyncio
async def test_summary_from_text_messages() -> None:
    provider = MockProvider(turns=[
        MockTurn(text="Edited /tmp/foo.py and added validation."),
    ])
    msgs = [
        NormalizedMessage(role="user", content="please add validation"),
        NormalizedMessage(role="assistant", content="OK done"),
    ]
    out = await generate_agent_summary(
        msgs, provider=provider, agent_name="bot",  # type: ignore[arg-type]
    )
    assert "Edited" in out
    assert "validation" in out


@pytest.mark.asyncio
async def test_summary_empty_messages_returns_fallback() -> None:
    provider = MockProvider()
    out = await generate_agent_summary(
        [], provider=provider, agent_name="bot",  # type: ignore[arg-type]
    )
    assert "no messages" in out.lower() or "[bot" in out


@pytest.mark.asyncio
async def test_summary_handles_tool_use_blocks() -> None:
    """訊息含 tool_use / tool_result block,format_messages 應正確攤平。"""
    provider = MockProvider(turns=[MockTurn(text="Ran a tool then summarized.")])
    msgs = [
        NormalizedMessage(
            role="assistant",
            content=[
                TextBlock(text="planning"),
                ToolUseBlock(id="t1", name="Read", input={"path": "/x"}),
            ],
        ),
    ]
    out = await generate_agent_summary(
        msgs, provider=provider, agent_name="bot",  # type: ignore[arg-type]
    )
    assert "Ran" in out


@pytest.mark.asyncio
async def test_summary_provider_failure_returns_fallback() -> None:
    """provider raises → 回 fallback,不傳出 exception。"""

    class _BoomProvider(MockProvider):
        async def stream(self, **kw):  # type: ignore[no-untyped-def,override]
            raise RuntimeError("kaboom")
            yield  # noqa  ─ unreachable but makes generator

    msgs = [NormalizedMessage(role="user", content="hi")]
    out = await generate_agent_summary(
        msgs, provider=_BoomProvider(), agent_name="bot",  # type: ignore[arg-type]
    )
    assert "without summary" in out


@pytest.mark.asyncio
async def test_summary_truncates_long_transcript() -> None:
    """太長 transcript → format 端截頭尾,不會塞爆 model。"""
    provider = MockProvider(turns=[MockTurn(text="ok")])
    big = "x" * 20000
    msgs = [NormalizedMessage(role="user", content=big)]
    await generate_agent_summary(
        msgs, provider=provider, agent_name="bot",  # type: ignore[arg-type]
    )
    # MockProvider 收到的 user_text 應含 truncated marker
    sent = provider.captured_calls[0]["messages"][0].content
    assert isinstance(sent, str)
    assert "truncated" in sent
