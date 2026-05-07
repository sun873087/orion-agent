"""EnterWorkdirTool / ExitWorkdirTool — push/pop cwd_stack + 驗證目錄。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import ErrorEvent, TextEvent, ToolEvent
from orion_agent.tools.workdir.enter import EnterWorkdirInput, EnterWorkdirTool
from orion_agent.tools.workdir.exit import ExitWorkdirInput, ExitWorkdirTool


async def _collect(it: AsyncIterator[ToolEvent]) -> list[ToolEvent]:
    return [ev async for ev in it]


@pytest.mark.asyncio
async def test_enter_pushes_and_changes_cwd(tmp_path: Path) -> None:
    ctx = AgentContext(cwd=Path("/tmp"))
    target = tmp_path
    tool = EnterWorkdirTool()
    events = await _collect(
        tool.call(EnterWorkdirInput(path=str(target)), ctx),
    )
    assert any(isinstance(e, TextEvent) for e in events)
    assert ctx.cwd == target
    assert ctx.cwd_stack == [Path("/tmp")]


@pytest.mark.asyncio
async def test_enter_rejects_relative() -> None:
    ctx = AgentContext()
    events = await _collect(
        EnterWorkdirTool().call(EnterWorkdirInput(path="rel/path"), ctx),
    )
    assert any(isinstance(e, ErrorEvent) for e in events)
    assert ctx.cwd_stack == []


@pytest.mark.asyncio
async def test_enter_missing_directory(tmp_path: Path) -> None:
    ctx = AgentContext()
    nope = tmp_path / "no-such"
    events = await _collect(
        EnterWorkdirTool().call(EnterWorkdirInput(path=str(nope)), ctx),
    )
    assert any(isinstance(e, ErrorEvent) for e in events)


@pytest.mark.asyncio
async def test_exit_pops(tmp_path: Path) -> None:
    ctx = AgentContext(cwd=Path("/tmp"))
    enter = EnterWorkdirTool()
    await _collect(enter.call(EnterWorkdirInput(path=str(tmp_path)), ctx))
    assert ctx.cwd == tmp_path

    exit_tool = ExitWorkdirTool()
    events = await _collect(exit_tool.call(ExitWorkdirInput(), ctx))
    assert any(isinstance(e, TextEvent) for e in events)
    assert ctx.cwd == Path("/tmp")
    assert ctx.cwd_stack == []


@pytest.mark.asyncio
async def test_exit_empty_stack() -> None:
    ctx = AgentContext()
    events = await _collect(ExitWorkdirTool().call(ExitWorkdirInput(), ctx))
    assert any(isinstance(e, ErrorEvent) for e in events)


@pytest.mark.asyncio
async def test_enter_exit_nested(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()

    ctx = AgentContext(cwd=Path("/tmp"))
    enter = EnterWorkdirTool()
    exit_t = ExitWorkdirTool()

    await _collect(enter.call(EnterWorkdirInput(path=str(a)), ctx))
    await _collect(enter.call(EnterWorkdirInput(path=str(b)), ctx))
    assert ctx.cwd == b
    assert ctx.cwd_stack == [Path("/tmp"), a]

    await _collect(exit_t.call(ExitWorkdirInput(), ctx))
    assert ctx.cwd == a

    await _collect(exit_t.call(ExitWorkdirInput(), ctx))
    assert ctx.cwd == Path("/tmp")
    assert ctx.cwd_stack == []
