"""ExitPlanModeTool — 提交 plan,等 user 批准。Phase 12。

對應 TS Claude Code `src/tools/ExitPlanModeTool/`。

呼叫即把 ctx.plan_mode_state 從 ACTIVE → AWAITING_APPROVAL,plan 寫進 plan_file,
所有後續工具(包括 read-only)直到 user 按 approve / reject 才會解鎖。

註:approve / reject 由前端 UI 處理 — 不是模型自己的工具。模型只能進入
AWAITING_APPROVAL,然後等。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from pydantic import Field

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput
from orion_sdk.plan_mode.state import (
    PlanModeState,
    PlanModeStatus,
    submit_plan,
)


class ExitPlanModeInput(ToolInput):
    """ExitPlanModeTool 的 input。"""

    plan: str = Field(
        ...,
        description=(
            "The final plan in markdown format. Should include: goal, "
            "concrete steps, files to modify, and any open questions. "
            "Will be presented to the user for approval before implementation."
        ),
    )


class ExitPlanModeTool:
    name = "ExitPlanMode"
    description = (
        "Submit your final plan and exit plan mode. After calling this, all "
        "tools are blocked until the user reviews and approves the plan. "
        "Provide the full plan in markdown — the user will see it verbatim."
    )
    input_schema = ExitPlanModeInput

    async def call(
        self,
        input: ExitPlanModeInput,
        ctx: AgentContext,
    ) -> AsyncIterator[ToolEvent]:
        current = ctx.plan_mode_state
        if not isinstance(current, PlanModeState):
            yield ErrorEvent(
                message=(
                    "Not in plan mode — nothing to exit. "
                    "Call EnterPlanMode first if you intended to enter plan mode."
                )
            )
            return

        if current.status == PlanModeStatus.AWAITING_APPROVAL:
            yield ErrorEvent(
                message=(
                    "Plan has already been submitted; awaiting user approval. "
                    "Wait for the user response before doing anything else."
                )
            )
            return

        if current.status != PlanModeStatus.ACTIVE:
            yield ErrorEvent(
                message=(
                    f"Cannot submit plan from status={current.status.value} "
                    "— EnterPlanMode first."
                )
            )
            return

        plan_text = input.plan.strip()
        if not plan_text:
            yield ErrorEvent(message="Plan content is empty.")
            return

        new_state = submit_plan(current, plan_text)
        ctx.plan_mode_state = new_state

        yield TextEvent(
            text=(
                "Plan submitted — awaiting user approval. All tools are now "
                "blocked until the user approves or rejects.\n"
                f"Plan file: {new_state.plan_file}\n"
                "—— PLAN ——\n"
                f"{plan_text}"
            )
        )

    def is_concurrency_safe(self, input: ExitPlanModeInput) -> bool:  # noqa: ARG002
        return False

    def is_read_only(self, input: ExitPlanModeInput) -> bool:  # noqa: ARG002
        return True

    def max_result_size_chars(self) -> int | float:
        return 50_000
