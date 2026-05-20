"""Plan mode state machine 測試。"""

from __future__ import annotations

from pathlib import Path

import pytest

from orion_sdk.plan_mode.state import (
    PlanModeState,
    PlanModeStatus,
    approve_and_exit,
    enter_plan_mode,
    reject_and_exit,
    submit_plan,
)


def test_initial_state_is_inactive() -> None:
    s = PlanModeState()
    assert s.status == PlanModeStatus.INACTIVE
    assert s.plan_id is None
    assert s.plan_file is None


def test_enter_plan_mode_creates_plan_file(tmp_path: Path) -> None:
    s = enter_plan_mode(PlanModeState(), plan_dir=tmp_path)
    assert s.status == PlanModeStatus.ACTIVE
    assert s.plan_id is not None
    assert s.plan_file is not None
    assert s.plan_file.exists()
    assert s.plan_file.parent == tmp_path


def test_enter_from_active_raises(tmp_path: Path) -> None:
    s = enter_plan_mode(PlanModeState(), plan_dir=tmp_path)
    with pytest.raises(ValueError, match="INACTIVE"):
        enter_plan_mode(s, plan_dir=tmp_path)


def test_submit_plan_writes_content(tmp_path: Path) -> None:
    active = enter_plan_mode(PlanModeState(), plan_dir=tmp_path)
    submitted = submit_plan(active, "## My plan\n- step 1\n- step 2\n")
    assert submitted.status == PlanModeStatus.AWAITING_APPROVAL
    assert submitted.plan_content.startswith("## My plan")
    assert submitted.plan_file is not None
    assert "step 1" in submitted.plan_file.read_text()


def test_submit_from_inactive_raises() -> None:
    with pytest.raises(ValueError, match="ACTIVE"):
        submit_plan(PlanModeState(), "x")


def test_approve_returns_to_inactive(tmp_path: Path) -> None:
    s = enter_plan_mode(PlanModeState(), plan_dir=tmp_path)
    s = submit_plan(s, "p")
    s = approve_and_exit(s)
    assert s.status == PlanModeStatus.INACTIVE
    assert s.plan_id is None


def test_approve_from_active_raises(tmp_path: Path) -> None:
    s = enter_plan_mode(PlanModeState(), plan_dir=tmp_path)
    with pytest.raises(ValueError, match="AWAITING_APPROVAL"):
        approve_and_exit(s)


def test_reject_from_awaiting(tmp_path: Path) -> None:
    s = enter_plan_mode(PlanModeState(), plan_dir=tmp_path)
    s = submit_plan(s, "p")
    s = reject_and_exit(s)
    assert s.status == PlanModeStatus.INACTIVE


def test_reject_from_active_also_works(tmp_path: Path) -> None:
    """Reject 也接受從 ACTIVE 直接退(user 中途取消)。"""
    s = enter_plan_mode(PlanModeState(), plan_dir=tmp_path)
    s = reject_and_exit(s)
    assert s.status == PlanModeStatus.INACTIVE


def test_reject_from_inactive_raises() -> None:
    with pytest.raises(ValueError):
        reject_and_exit(PlanModeState())


def test_state_is_frozen() -> None:
    """PlanModeState 是 frozen dataclass — 不可直接 mutate。"""
    s = PlanModeState()
    with pytest.raises((AttributeError, Exception)):
        s.status = PlanModeStatus.ACTIVE # type: ignore[misc]
