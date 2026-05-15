"""Plan mode 工具限制 + plan_mode_aware wrapper 測試。Phase 12。"""

from __future__ import annotations

from typing import Any

import pytest

from orion_sdk.core.state import AgentContext
from orion_sdk.permissions.decisions import (
    PermissionDecision,
    PermissionResult,
    always_allow,
)
from orion_sdk.plan_mode.restrictions import (
    PLAN_MODE_ALLOWED_TOOLS,
    is_tool_allowed_in_plan_mode,
    plan_mode_aware,
)
from orion_sdk.plan_mode.state import (
    PlanModeState,
    PlanModeStatus,
    enter_plan_mode,
    submit_plan,
)


def test_inactive_allows_all() -> None:
    s = PlanModeState()
    assert is_tool_allowed_in_plan_mode("Edit", s) is True
    assert is_tool_allowed_in_plan_mode("Bash", s) is True


def test_active_allows_read_only() -> None:
    s = PlanModeState(status=PlanModeStatus.ACTIVE)
    for name in PLAN_MODE_ALLOWED_TOOLS:
        assert is_tool_allowed_in_plan_mode(name, s) is True


def test_active_denies_write_tools() -> None:
    s = PlanModeState(status=PlanModeStatus.ACTIVE)
    for name in ("Edit", "Write", "Bash", "Agent"):
        assert is_tool_allowed_in_plan_mode(name, s) is False


def test_awaiting_denies_everything() -> None:
    s = PlanModeState(status=PlanModeStatus.AWAITING_APPROVAL)
    for name in ("Read", "Grep", "ExitPlanMode", "Edit", "Bash"):
        assert is_tool_allowed_in_plan_mode(name, s) is False


class _FakeTool:
    """可重用的假 tool — 對 Tool Protocol 而言 name 即可。"""

    def __init__(self, name: str) -> None:
        self.name = name


@pytest.mark.asyncio
async def test_wrapper_passes_through_when_inactive() -> None:
    inner = always_allow
    wrapped = plan_mode_aware(inner)
    ctx = AgentContext()  # plan_mode_state 為 None → 視同 INACTIVE
    res = await wrapped(_FakeTool("Edit"), {}, ctx)  # type: ignore[arg-type]
    assert res.decision == PermissionDecision.ALLOW


@pytest.mark.asyncio
async def test_wrapper_denies_write_in_active(tmp_path: Any) -> None:
    inner = always_allow
    wrapped = plan_mode_aware(inner)
    ctx = AgentContext()
    ctx.plan_mode_state = enter_plan_mode(PlanModeState(), plan_dir=tmp_path)

    res_edit = await wrapped(_FakeTool("Edit"), {}, ctx)  # type: ignore[arg-type]
    assert res_edit.decision == PermissionDecision.DENY
    assert "plan mode" in res_edit.reason.lower()

    res_read = await wrapped(_FakeTool("Read"), {}, ctx)  # type: ignore[arg-type]
    assert res_read.decision == PermissionDecision.ALLOW


@pytest.mark.asyncio
async def test_wrapper_denies_all_in_awaiting(tmp_path: Any) -> None:
    wrapped = plan_mode_aware(always_allow)
    ctx = AgentContext()
    s = enter_plan_mode(PlanModeState(), plan_dir=tmp_path)
    s = submit_plan(s, "plan")
    ctx.plan_mode_state = s

    for name in ("Read", "Edit", "ExitPlanMode"):
        res = await wrapped(_FakeTool(name), {}, ctx)  # type: ignore[arg-type]
        assert res.decision == PermissionDecision.DENY
        assert "approval" in res.reason.lower()


@pytest.mark.asyncio
async def test_wrapper_respects_inner_when_allowed(tmp_path: Any) -> None:
    """Plan mode 通過後仍交給 inner 決定 — inner 拒絕仍然拒絕。"""

    async def inner_deny(*_args: Any, **_kw: Any) -> PermissionResult:
        return PermissionResult(decision=PermissionDecision.DENY, reason="inner deny")

    wrapped = plan_mode_aware(inner_deny)
    ctx = AgentContext()
    ctx.plan_mode_state = enter_plan_mode(PlanModeState(), plan_dir=tmp_path)

    # Read 在白名單 → plan_mode 通過 → 但 inner deny
    res = await wrapped(_FakeTool("Read"), {}, ctx)  # type: ignore[arg-type]
    assert res.decision == PermissionDecision.DENY
    assert "inner deny" in res.reason
