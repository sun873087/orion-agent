"""ToolSearchTool — select / keyword search / 找不到。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import TextEvent, ToolEvent, ToolInput
from orion_agent.tools.special.tool_search import ToolSearchInput, ToolSearchTool


class _DummyInputA(ToolInput):
    pass


class _DummyToolA:
    name = "Alpha"
    description = "alpha tool for testing"
    input_schema = _DummyInputA

    async def call(
        self, input: _DummyInputA, ctx: AgentContext,  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        return
        yield  # pragma: no cover

    def is_concurrency_safe(self, input: _DummyInputA) -> bool:  # noqa: ARG002
        return True

    def is_read_only(self, input: _DummyInputA) -> bool:  # noqa: ARG002
        return True

    def max_result_size_chars(self) -> int | float:
        return 1_000


class _DummyInputB(ToolInput):
    pass


class _DummyToolB:
    name = "Beta"
    description = "completely different bravo tool"
    input_schema = _DummyInputB

    async def call(
        self, input: _DummyInputB, ctx: AgentContext,  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        return
        yield  # pragma: no cover

    def is_concurrency_safe(self, input: _DummyInputB) -> bool:  # noqa: ARG002
        return True

    def is_read_only(self, input: _DummyInputB) -> bool:  # noqa: ARG002
        return True

    def max_result_size_chars(self) -> int | float:
        return 1_000


async def _collect(it: AsyncIterator[ToolEvent]) -> list[ToolEvent]:
    return [ev async for ev in it]


@pytest.mark.asyncio
async def test_select_specific() -> None:
    tool = ToolSearchTool(all_tools=[_DummyToolA(), _DummyToolB()])  # type: ignore[list-item]
    events = await _collect(
        tool.call(ToolSearchInput(query="select:Alpha"), AgentContext()),
    )
    text = next(e.text for e in events if isinstance(e, TextEvent))
    assert "Alpha" in text
    assert "Beta" not in text
    assert "<functions>" in text


@pytest.mark.asyncio
async def test_select_multiple() -> None:
    tool = ToolSearchTool(all_tools=[_DummyToolA(), _DummyToolB()])  # type: ignore[list-item]
    events = await _collect(
        tool.call(ToolSearchInput(query="select:Alpha,Beta"), AgentContext()),
    )
    text = next(e.text for e in events if isinstance(e, TextEvent))
    assert "Alpha" in text
    assert "Beta" in text


@pytest.mark.asyncio
async def test_keyword_search() -> None:
    tool = ToolSearchTool(all_tools=[_DummyToolA(), _DummyToolB()])  # type: ignore[list-item]
    events = await _collect(
        tool.call(ToolSearchInput(query="bravo"), AgentContext()),
    )
    text = next(e.text for e in events if isinstance(e, TextEvent))
    assert "Beta" in text
    assert "Alpha" not in text


@pytest.mark.asyncio
async def test_no_match() -> None:
    tool = ToolSearchTool(all_tools=[_DummyToolA()])  # type: ignore[list-item]
    events = await _collect(
        tool.call(ToolSearchInput(query="select:NotExisting"), AgentContext()),
    )
    text = next(e.text for e in events if isinstance(e, TextEvent))
    assert "No tools matched" in text


@pytest.mark.asyncio
async def test_required_keyword_filter() -> None:
    """+keyword 強制要包含。"""
    tool = ToolSearchTool(all_tools=[_DummyToolA(), _DummyToolB()])  # type: ignore[list-item]
    events = await _collect(
        tool.call(ToolSearchInput(query="+alpha tool"), AgentContext()),
    )
    text = next(e.text for e in events if isinstance(e, TextEvent))
    assert "Alpha" in text
    assert "Beta" not in text


def test_update_tools_replaces_list() -> None:
    tool = ToolSearchTool(all_tools=[_DummyToolA()])  # type: ignore[list-item]
    assert len(tool.all_tools) == 1
    tool.update_tools([_DummyToolA(), _DummyToolB()])  # type: ignore[list-item]
    assert len(tool.all_tools) == 2
