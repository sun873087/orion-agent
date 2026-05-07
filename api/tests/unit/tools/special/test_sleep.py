"""SleepTool — abort 立即中斷,正常 sleep 60s。"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator

import anyio
import pytest

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import TextEvent, ToolEvent
from orion_agent.tools.special.sleep import SleepInput, SleepTool


async def _collect(it: AsyncIterator[ToolEvent]) -> list[ToolEvent]:
    return [ev async for ev in it]


@pytest.mark.asyncio
async def test_abort_interrupts_sleep_quickly() -> None:
    ctx = AgentContext()
    tool = SleepTool()
    start = time.monotonic()

    async def trigger_abort() -> None:
        await anyio.sleep(0.1)
        ctx.abort_event.set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(trigger_abort)
        events = await _collect(tool.call(SleepInput(seconds=3600), ctx))

    elapsed = time.monotonic() - start
    assert elapsed < 1.0  # abort 中斷,不該等 3600s
    assert any(isinstance(e, TextEvent) for e in events)


@pytest.mark.asyncio
async def test_min_seconds_clamp() -> None:
    """input 自動 schema 驗證 ge=60,< 60 應 reject。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SleepInput(seconds=10)
