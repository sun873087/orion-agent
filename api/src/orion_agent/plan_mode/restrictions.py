"""Plan mode 工具限制。

ACTIVE 狀態:只允許 read-only / 規劃類工具。
AWAITING_APPROVAL 狀態:任何工具 deny(等 user 按鈕)。
INACTIVE 狀態:不限制(交給原本的 can_use_tool)。

對應 TS Claude Code `src/utils/planModeV2.ts` 的工具白名單。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from orion_agent.permissions.decisions import (
    CanUseToolFn,
    PermissionDecision,
    PermissionResult,
)
from orion_agent.plan_mode.state import PlanModeState, PlanModeStatus

if TYPE_CHECKING:
    from orion_agent.core.state import AgentContext
    from orion_agent.core.tool import Tool


PLAN_MODE_ALLOWED_TOOLS: frozenset[str] = frozenset({
    # 讀取 / 搜尋 — 純 read-only
    "Read",
    "Grep",
    "Glob",
    "WebFetch",
    "WebSearch",
    # 規劃 / 描述輸出 — 不動 fs
    "TodoWrite",  # 寫的是 in-memory todos,不動 fs
    # 結束 plan mode 必經
    "ExitPlanMode",
    # 進階查詢:子 agent 用 — 子 agent 自己有獨立 plan_mode_state
    # (但 plan mode 下 spawn 子 agent 風險高,先不放白名單)
    # "Agent",  # ← 故意註解,plan mode 下不允許 spawn
})
"""Plan mode ACTIVE 時允許的工具白名單。"""


def is_tool_allowed_in_plan_mode(tool_name: str, plan_state: PlanModeState) -> bool:
    """檢查工具是否在當前 plan mode 狀態下允許。

    - INACTIVE → 全部允許(本函式不該決定 INACTIVE 的事;但守門上 return True)
    - ACTIVE → 只允許 PLAN_MODE_ALLOWED_TOOLS
    - AWAITING_APPROVAL → 一律拒絕(即使 read-only)— 等 user 按 approve

    Args:
        tool_name: 工具名(對應 Tool.name)。
        plan_state: 當前 PlanModeState。

    Returns:
        bool — True = 允許走後續 policy;False = 直接 deny。
    """
    if plan_state.status == PlanModeStatus.INACTIVE:
        return True
    if plan_state.status == PlanModeStatus.AWAITING_APPROVAL:
        return False
    # ACTIVE
    return tool_name in PLAN_MODE_ALLOWED_TOOLS


def plan_mode_aware(
    inner: CanUseToolFn,
) -> CanUseToolFn:
    """把既有 CanUseToolFn 包成 plan-mode-aware 版本。

    Plan mode 限制優先於 inner policy:plan mode 拒絕 → 直接 deny;
    plan mode 通過 → 交給 inner 決定。

    Reads `ctx.plan_mode_state`(PlanModeState | None);若 ctx 沒有此屬性 / 為 None,
    視同 INACTIVE,直接交給 inner。
    """

    async def wrapped(
        tool: Tool[Any],
        tool_input: dict[str, Any],
        ctx: AgentContext,
    ) -> PermissionResult:
        plan_state = getattr(ctx, "plan_mode_state", None)
        if isinstance(plan_state, PlanModeState) and not is_tool_allowed_in_plan_mode(
            tool.name, plan_state,
        ):
            if plan_state.status == PlanModeStatus.AWAITING_APPROVAL:
                reason = (
                    f"Plan awaiting user approval — '{tool.name}' is not "
                    "allowed until the plan is approved or rejected."
                )
            else:
                reason = (
                    f"Plan mode is active — '{tool.name}' is not in the "
                    "read-only allow list. Use Read/Grep/Glob/WebFetch only."
                )
            return PermissionResult(
                decision=PermissionDecision.DENY,
                reason=reason,
            )
        return await inner(tool, tool_input, ctx)

    return wrapped


__all__ = [
    "PLAN_MODE_ALLOWED_TOOLS",
    "is_tool_allowed_in_plan_mode",
    "plan_mode_aware",
]
