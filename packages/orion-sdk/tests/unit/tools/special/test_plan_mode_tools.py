"""EnterPlanMode / ExitPlanMode 工具測試。"""

from __future__ import annotations

from pathlib import Path

import pytest

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent
from orion_sdk.plan_mode.state import (
    PlanModeState,
    PlanModeStatus,
)
from orion_sdk.tools.special.enter_plan_mode import (
    EnterPlanModeInput,
    EnterPlanModeTool,
)
from orion_sdk.tools.special.exit_plan_mode import (
    ExitPlanModeInput,
    ExitPlanModeTool,
)


@pytest.mark.asyncio
async def test_enter_from_inactive(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ORION_HOME", str(tmp_path))
    ctx = AgentContext()
    tool = EnterPlanModeTool()
    events = [e async for e in tool.call(EnterPlanModeInput(), ctx)]
    assert isinstance(events[0], TextEvent)
    assert isinstance(ctx.plan_mode_state, PlanModeState)
    assert ctx.plan_mode_state.status == PlanModeStatus.ACTIVE
    assert ctx.plan_mode_state.plan_file is not None
    assert ctx.plan_mode_state.plan_file.exists()


@pytest.mark.asyncio
async def test_enter_when_already_active_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ORION_HOME", str(tmp_path))
    ctx = AgentContext()
    tool = EnterPlanModeTool()
    [_ async for _ in tool.call(EnterPlanModeInput(), ctx)]
    events = [e async for e in tool.call(EnterPlanModeInput(), ctx)]
    assert isinstance(events[0], ErrorEvent)
    assert "already" in events[0].message.lower()


@pytest.mark.asyncio
async def test_exit_outside_plan_mode_errors() -> None:
    ctx = AgentContext()
    tool = ExitPlanModeTool()
    events = [e async for e in tool.call(ExitPlanModeInput(plan="x"), ctx)]
    assert isinstance(events[0], ErrorEvent)
    assert "not in plan mode" in events[0].message.lower()


@pytest.mark.asyncio
async def test_exit_from_active_transitions_to_awaiting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ORION_HOME", str(tmp_path))
    ctx = AgentContext()
    enter = EnterPlanModeTool()
    [_ async for _ in enter.call(EnterPlanModeInput(), ctx)]

    exit_tool = ExitPlanModeTool()
    plan_md = "## Plan\n- step A\n- step B"
    events = [
        e async for e in exit_tool.call(ExitPlanModeInput(plan=plan_md), ctx)
    ]
    assert isinstance(events[0], TextEvent)
    assert "step A" in events[0].text

    state = ctx.plan_mode_state
    assert isinstance(state, PlanModeState)
    assert state.status == PlanModeStatus.AWAITING_APPROVAL
    assert state.plan_content == plan_md
    assert state.plan_file is not None
    assert "step B" in state.plan_file.read_text()


@pytest.mark.asyncio
async def test_exit_with_empty_plan_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ORION_HOME", str(tmp_path))
    ctx = AgentContext()
    [_ async for _ in EnterPlanModeTool().call(EnterPlanModeInput(), ctx)]
    events = [
        e async for e in ExitPlanModeTool().call(ExitPlanModeInput(plan=" "), ctx)
    ]
    assert isinstance(events[0], ErrorEvent)
    assert "empty" in events[0].message.lower()


@pytest.mark.asyncio
async def test_exit_twice_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ORION_HOME", str(tmp_path))
    ctx = AgentContext()
    [_ async for _ in EnterPlanModeTool().call(EnterPlanModeInput(), ctx)]
    [_ async for _ in ExitPlanModeTool().call(ExitPlanModeInput(plan="p"), ctx)]
    events = [
        e async for e in ExitPlanModeTool().call(ExitPlanModeInput(plan="q"), ctx)
    ]
    assert isinstance(events[0], ErrorEvent)
    assert "awaiting" in events[0].message.lower()
