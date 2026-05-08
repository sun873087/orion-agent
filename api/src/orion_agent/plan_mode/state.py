"""Plan mode state machine。對應 TS planModeV2 + EnterPlanMode/ExitPlanMode 工具。

三態 + 三個轉換函式:
  INACTIVE → enter_plan_mode → ACTIVE
  ACTIVE   → submit_plan     → AWAITING_APPROVAL
  AWAITING_APPROVAL → approve_and_exit → INACTIVE

state machine 故意設計成 **immutable update**:每個轉換回傳新 PlanModeState,
caller 自行替換 ctx 上的 state。這對 race / multi-task 較安全。
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid4


class PlanModeStatus(StrEnum):
    """Plan mode 三態。"""

    INACTIVE = "inactive"
    """正常模式 — 工具不受限。"""

    ACTIVE = "active"
    """進 plan mode — 工具白名單(read-only)。"""

    AWAITING_APPROVAL = "awaiting_approval"
    """模型 call ExitPlanMode 後 — plan 寫好等 user 按鈕,所有工具 deny。"""


@dataclass(frozen=True)
class PlanModeState:
    """Plan mode 狀態(immutable)。"""

    status: PlanModeStatus = PlanModeStatus.INACTIVE
    plan_id: UUID | None = None
    """進入 plan mode 時隨機生成,供 plan_file 命名。"""

    plan_file: Path | None = None
    """plan 寫到的檔案(供 user review)。"""

    plan_content: str = ""
    """ExitPlanMode 時模型寫的 plan 內容(submit 時填入)。"""

    entered_at_message_index: int | None = None
    """進入 plan mode 時的 conversation message index(便於 abort 時 rewind)。"""


def enter_plan_mode(
    state: PlanModeState,
    *,
    plan_dir: Path,
    message_index: int | None = None,
) -> PlanModeState:
    """INACTIVE → ACTIVE。

    建立空 plan_file 占位(即使尚未寫內容,有檔表示「正在 planning」)。

    Raises:
        ValueError: 若 state 非 INACTIVE。
    """
    if state.status != PlanModeStatus.INACTIVE:
        raise ValueError(
            f"Cannot enter plan mode from status={state.status.value} "
            "(must be INACTIVE)"
        )
    plan_id = uuid4()
    plan_dir.mkdir(parents=True, exist_ok=True)
    plan_file = plan_dir / f"plan-{plan_id.hex[:12]}.md"
    plan_file.touch()
    return PlanModeState(
        status=PlanModeStatus.ACTIVE,
        plan_id=plan_id,
        plan_file=plan_file,
        plan_content="",
        entered_at_message_index=message_index,
    )


def submit_plan(state: PlanModeState, plan_content: str) -> PlanModeState:
    """ACTIVE → AWAITING_APPROVAL。模型 call ExitPlanMode 時用。

    把 plan_content 寫進 plan_file(供 user review),狀態轉 AWAITING_APPROVAL —
    後續所有工具(連 read-only 也)都 deny,直到 user 按 approve。

    Raises:
        ValueError: 若 state 非 ACTIVE。
    """
    if state.status != PlanModeStatus.ACTIVE:
        raise ValueError(
            f"Cannot submit plan from status={state.status.value} "
            "(must be ACTIVE)"
        )
    if state.plan_file is not None:
        # 寫檔失敗不阻擋狀態轉換 — plan_content 在 state 上仍可取
        with contextlib.suppress(OSError):
            state.plan_file.write_text(plan_content, encoding="utf-8")
    return PlanModeState(
        status=PlanModeStatus.AWAITING_APPROVAL,
        plan_id=state.plan_id,
        plan_file=state.plan_file,
        plan_content=plan_content,
        entered_at_message_index=state.entered_at_message_index,
    )


def approve_and_exit(state: PlanModeState) -> PlanModeState:
    """AWAITING_APPROVAL → INACTIVE。User 按 approve 時用。

    回到 INACTIVE 並丟棄 plan 引用(plan_file 仍在 disk,user 可手動讀)。

    Raises:
        ValueError: 若 state 非 AWAITING_APPROVAL。
    """
    if state.status != PlanModeStatus.AWAITING_APPROVAL:
        raise ValueError(
            f"Cannot approve_and_exit from status={state.status.value} "
            "(must be AWAITING_APPROVAL)"
        )
    return PlanModeState(status=PlanModeStatus.INACTIVE)


def reject_and_exit(state: PlanModeState) -> PlanModeState:
    """AWAITING_APPROVAL → INACTIVE(user reject)。

    與 approve 行為相同(轉回 INACTIVE),但可由 caller 區分 — 例:reject 時把
    plan_file 刪掉、或塞訊息給模型重新 plan。
    """
    if state.status not in (PlanModeStatus.AWAITING_APPROVAL, PlanModeStatus.ACTIVE):
        raise ValueError(
            f"Cannot reject from status={state.status.value} "
            "(must be ACTIVE or AWAITING_APPROVAL)"
        )
    return PlanModeState(status=PlanModeStatus.INACTIVE)


__all__ = [
    "PlanModeState",
    "PlanModeStatus",
    "approve_and_exit",
    "enter_plan_mode",
    "reject_and_exit",
    "submit_plan",
]
