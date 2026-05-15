"""Tool Protocol runtime check + 預設方法回傳值。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import TextEvent, Tool, ToolEvent, ToolInput


class DummyInput(ToolInput):
    text: str


class DummyTool:
    name = "Dummy"
    description = "just for testing"
    input_schema = DummyInput

    async def call(
        self, input: DummyInput, ctx: AgentContext  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        yield TextEvent(text=f"echo: {input.text}")

    def is_concurrency_safe(self, input: DummyInput) -> bool:  # noqa: ARG002
        return True

    def is_read_only(self, input: DummyInput) -> bool:  # noqa: ARG002
        return True

    def max_result_size_chars(self) -> int | float:
        return 1_000


def test_dummy_tool_is_runtime_tool() -> None:
    assert isinstance(DummyTool(), Tool)


def test_dummy_tool_metadata() -> None:
    t = DummyTool()
    assert t.name == "Dummy"
    assert t.is_read_only(DummyInput(text="x")) is True
    assert t.is_concurrency_safe(DummyInput(text="x")) is True
    assert t.max_result_size_chars() == 1_000


@pytest.mark.asyncio
async def test_dummy_tool_call_yields_text(tmp_ctx: AgentContext) -> None:
    t = DummyTool()
    out: list[ToolEvent] = []
    async for e in t.call(DummyInput(text="hi"), tmp_ctx):
        out.append(e)
    assert len(out) == 1
    assert isinstance(out[0], TextEvent)
    assert out[0].text == "echo: hi"
