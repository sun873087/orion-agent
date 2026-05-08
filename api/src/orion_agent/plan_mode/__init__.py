"""Plan mode 機制 — Phase 12。

Plan mode 是「模型只讀規劃,不寫任何檔」的特殊狀態。三態:
  - INACTIVE:正常模式
  - ACTIVE:模型在 plan,工具受限為 read-only 白名單
  - AWAITING_APPROVAL:模型 call ExitPlanMode → plan 寫好等使用者按鈕,任何工具皆 deny

對應 TS Claude Code:
- `src/utils/planModeV2.ts`(state machine + restrictions)
- `src/tools/EnterPlanModeTool/`、`src/tools/ExitPlanModeTool/`
"""

from orion_agent.plan_mode.restrictions import (
    PLAN_MODE_ALLOWED_TOOLS,
    is_tool_allowed_in_plan_mode,
    plan_mode_aware,
)
from orion_agent.plan_mode.state import (
    PlanModeState,
    PlanModeStatus,
    approve_and_exit,
    enter_plan_mode,
    submit_plan,
)

__all__ = [
    "PLAN_MODE_ALLOWED_TOOLS",
    "PlanModeState",
    "PlanModeStatus",
    "approve_and_exit",
    "enter_plan_mode",
    "is_tool_allowed_in_plan_mode",
    "plan_mode_aware",
    "submit_plan",
]
