"""SyntheticOutputTool — caller 自訂 schema → tool 收 + 存 last_output。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from pydantic import BaseModel, Field

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import TextEvent, ToolEvent
from orion_sdk.tools.special.synthetic_output import SyntheticOutputTool


class _Result(BaseModel):
    """User schema:findings + verdict。"""

    findings: list[str] = Field(default_factory=list)
    verdict: str = ""


async def _collect(it: AsyncIterator[ToolEvent]) -> list[ToolEvent]:
    return [ev async for ev in it]


@pytest.mark.asyncio
async def test_records_last_output() -> None:
    tool = SyntheticOutputTool(schema=_Result)
    payload = _Result(findings=["bug A", "bug B"], verdict="fix")
    events = await _collect(tool.call(payload, AgentContext()))
    assert any(isinstance(e, TextEvent) for e in events)
    assert tool.last_output == {"findings": ["bug A", "bug B"], "verdict": "fix"}


@pytest.mark.asyncio
async def test_default_schema_extra_allowed() -> None:
    """無 schema 時用預設 input,允許 extra fields。"""
    tool = SyntheticOutputTool()
    # SyntheticOutputInput allows extra, validate from dict
    parsed = tool.input_schema.model_validate({"x": 1, "y": "hi"})
    await _collect(tool.call(parsed, AgentContext()))
    assert tool.last_output is not None
