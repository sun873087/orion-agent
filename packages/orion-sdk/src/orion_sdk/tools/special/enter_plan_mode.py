"""EnterPlanModeTool — 進入 plan mode。Phase 12。

對應 TS Claude Code `src/tools/EnterPlanModeTool/`。

呼叫即把 ctx.plan_mode_state 從 INACTIVE → ACTIVE,後續工具受 read-only 白名單限制。
模型在 ACTIVE 狀態下用 Read / Grep / Glob 探索,把計畫整理好,最後 call ExitPlanMode。

通常由前端 UI 觸發(user 按 "Plan Mode" 按鈕)— 模型也可主動呼叫(用於探索類任務)。
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput
from orion_sdk.plan_mode.state import (
    PlanModeState,
    PlanModeStatus,
    enter_plan_mode,
)


def _default_plan_dir() -> Path:
    """預設 plan 寫入位置:`$ORION_HOME/plans/`(若無 env,用 `~/.orion/plans/`)。"""
    base = os.environ.get("ORION_HOME")
    if base:
        return Path(base) / "plans"
    return Path.home() / ".orion" / "plans"


class EnterPlanModeInput(ToolInput):
    """EnterPlanModeTool 的 input — 故意空(無參數)。"""


class EnterPlanModeTool:
    name = "EnterPlanMode"
    description = (
        "Enter plan mode. While active, only read-only tools (Read/Grep/Glob/"
        "WebFetch/WebSearch/TodoWrite) are allowed. Use this when the user "
        "asks for analysis/planning before making changes. Exit by calling "
        "ExitPlanMode with the final plan."
    )
    input_schema = EnterPlanModeInput

    async def call(
        self,
        input: EnterPlanModeInput,  # noqa: ARG002
        ctx: AgentContext,
    ) -> AsyncIterator[ToolEvent]:
        current = ctx.plan_mode_state
        existing = current if isinstance(current, PlanModeState) else PlanModeState()

        if existing.status != PlanModeStatus.INACTIVE:
            yield ErrorEvent(
                message=(
                    f"Already in plan mode (status={existing.status.value}). "
                    "Call ExitPlanMode to leave first."
                )
            )
            return

        try:
            new_state = enter_plan_mode(existing, plan_dir=_default_plan_dir())
        except OSError as e:
            yield ErrorEvent(message=f"Failed to create plan directory: {e}")
            return

        ctx.plan_mode_state = new_state
        plan_path = new_state.plan_file
        yield TextEvent(
            text=(
                "Entered plan mode. Read-only tools are now enforced. "
                f"Plan file: {plan_path}\n"
                "Investigate the codebase, then call ExitPlanMode with your final plan."
            )
        )

    def is_concurrency_safe(self, input: EnterPlanModeInput) -> bool:  # noqa: ARG002
        return False  # mutates ctx state

    def is_read_only(self, input: EnterPlanModeInput) -> bool:  # noqa: ARG002
        # 純切狀態,不寫檔案內容
        return True

    def max_result_size_chars(self) -> int | float:
        return 500
