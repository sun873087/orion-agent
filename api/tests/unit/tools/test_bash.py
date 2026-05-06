"""BashTool。"""

from __future__ import annotations

import pytest

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import ErrorEvent, TextEvent
from orion_agent.tools.shell.bash import BashInput, BashTool


@pytest.mark.asyncio
async def test_echo() -> None:
    tool = BashTool()
    events = [
        e
        async for e in tool.call(
            BashInput(command="echo hello"), AgentContext()
        )
    ]
    assert isinstance(events[0], TextEvent)
    assert "hello" in events[0].text
    assert "[exit 0]" in events[0].text


@pytest.mark.asyncio
async def test_nonzero_exit_marked_error() -> None:
    tool = BashTool()
    events = [
        e
        async for e in tool.call(
            BashInput(command="exit 7"), AgentContext()
        )
    ]
    assert isinstance(events[0], ErrorEvent)
    assert "[exit 7]" in events[0].message


@pytest.mark.asyncio
async def test_timeout() -> None:
    tool = BashTool()
    events = [
        e
        async for e in tool.call(
            BashInput(command="sleep 5", timeout_seconds=1), AgentContext()
        )
    ]
    assert isinstance(events[0], ErrorEvent)
    assert "timed out" in events[0].message.lower()


@pytest.mark.asyncio
async def test_relative_cwd_rejected() -> None:
    tool = BashTool()
    events = [
        e
        async for e in tool.call(
            BashInput(command="pwd", cwd="relative"), AgentContext()
        )
    ]
    assert isinstance(events[0], ErrorEvent)
    assert "absolute" in events[0].message.lower()


def test_metadata() -> None:
    tool = BashTool()
    inp = BashInput(command="x")
    assert tool.is_concurrency_safe(inp) is False
    assert tool.is_read_only(inp) is False
