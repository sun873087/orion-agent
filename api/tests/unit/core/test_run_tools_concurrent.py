"""run_tools_concurrently — order preservation + capacity limiter。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import anyio
import pytest

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import TextEvent, ToolEvent, ToolInput
from orion_agent.core.tool_execution import ToolResultUpdate
from orion_agent.core.tool_orchestration import (
    get_max_concurrency,
    run_tools,
)
from orion_agent.hooks.registry import HookRegistry
from orion_agent.llm.types import ToolUseBlock
from orion_agent.permissions.decisions import always_allow


class _SlowReadInput(ToolInput):
    delay: float
    label: str


class _SlowReadTool:
    name = "SlowRead"
    description = "x"
    input_schema = _SlowReadInput

    async def call(
        self, input: _SlowReadInput, ctx: AgentContext  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        await anyio.sleep(input.delay)
        yield TextEvent(text=f"got {input.label}")

    def is_concurrency_safe(self, _: _SlowReadInput) -> bool:
        return True

    def is_read_only(self, _: _SlowReadInput) -> bool:
        return True

    def max_result_size_chars(self) -> int | float:
        return 10_000


@pytest.mark.asyncio
async def test_order_preserved_despite_completion_race() -> None:
    """3 個並發 SlowRead,延遲 0.3 / 0.1 / 0.2,結果順序仍是 a, b, c。"""
    tool = _SlowReadTool()
    blocks = [
        ToolUseBlock(id="a", name="SlowRead", input={"delay": 0.3, "label": "a"}),
        ToolUseBlock(id="b", name="SlowRead", input={"delay": 0.1, "label": "b"}),
        ToolUseBlock(id="c", name="SlowRead", input={"delay": 0.2, "label": "c"}),
    ]
    results: list[ToolResultUpdate] = []
    async for upd in run_tools(
        blocks,
        tools=[tool],  # type: ignore[list-item]
        can_use_tool=always_allow,
        hooks=HookRegistry(),
        ctx=AgentContext(),
    ):
        if isinstance(upd, ToolResultUpdate):
            results.append(upd)

    ids_in_order = [r.tool_use_id for r in results]
    assert ids_in_order == ["a", "b", "c"]


def test_capacity_limiter_default() -> None:
    """預設 10。"""
    assert get_max_concurrency() == 10


def test_capacity_limiter_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORION_MAX_TOOL_CONCURRENCY", "3")
    assert get_max_concurrency() == 3


def test_capacity_limiter_invalid_env_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORION_MAX_TOOL_CONCURRENCY", "garbage")
    assert get_max_concurrency() == 10


def test_capacity_limiter_zero_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORION_MAX_TOOL_CONCURRENCY", "0")
    assert get_max_concurrency() == 1
