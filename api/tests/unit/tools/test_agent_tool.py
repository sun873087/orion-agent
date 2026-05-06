"""AgentTool — 用 MockProvider 驗 spawn 子 agent。"""

from __future__ import annotations

import pytest

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import ErrorEvent, TextEvent
from orion_agent.tools.agent.agent_tool import AgentTool, AgentToolInput
from orion_agent.tools.file.read import FileReadTool
from tests.conftest import MockProvider, MockTurn


@pytest.mark.asyncio
async def test_sub_agent_returns_text(sample_text_file: object) -> None:
    """子 agent 跑一輪 text-only,parent 收到 final text。"""
    provider = MockProvider(turns=[MockTurn(text="42")])
    tool = AgentTool(provider=provider, child_tools=[FileReadTool()])  # type: ignore[arg-type]
    events = [
        e
        async for e in tool.call(
            AgentToolInput(task="What is the answer?"), AgentContext()
        )
    ]
    assert isinstance(events[0], TextEvent)
    assert "42" in events[0].text


@pytest.mark.asyncio
async def test_sub_agent_depth_limit() -> None:
    """sub_agent_depth >= 1 → AgentTool 拒絕執行。"""
    provider = MockProvider(turns=[MockTurn(text="x")])
    tool = AgentTool(provider=provider, child_tools=[])  # type: ignore[arg-type]
    deep_ctx = AgentContext(sub_agent_depth=1)
    events = [
        e
        async for e in tool.call(AgentToolInput(task="x"), deep_ctx)
    ]
    assert isinstance(events[0], ErrorEvent)
    assert "nested" in events[0].message.lower() or "depth" in events[0].message.lower()


def test_self_reference_filtered() -> None:
    """child_tools 含 AgentTool 自己 → 自動過濾掉。"""
    provider = MockProvider()
    other = AgentTool(provider=provider, child_tools=[])  # type: ignore[arg-type]
    tool = AgentTool(
        provider=provider,  # type: ignore[arg-type]
        child_tools=[FileReadTool(), other],  # type: ignore[list-item]
    )
    names = [t.name for t in tool.child_tools]
    assert "Agent" not in names
    assert "Read" in names
