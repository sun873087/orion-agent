"""Hook event 型別。

Phase 1 只有 PreToolUse / PostToolUse — Phase 8 會加 SessionStart / Stop / Notification 等。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from orion_agent.core.state import AgentContext
    from orion_agent.core.tool import Tool


@dataclass
class PreToolUseEvent:
    """工具執行前。Hook 可:
    - 回 None / True → 放行
    - 回 False → 視同 permission deny(不執行,回 synthetic error 給模型)
    - raise exception → 中斷整個 query_loop
    """

    type: Literal["pre_tool_use"] = "pre_tool_use"
    tool: Tool[Any] | None = None
    tool_input: dict[str, Any] | None = None
    ctx: AgentContext | None = None


@dataclass
class PostToolUseEvent:
    """工具執行後。Hook 可看結果(read-only),用於 logging / telemetry。
    回傳值忽略。
    """

    type: Literal["post_tool_use"] = "post_tool_use"
    tool: Tool[Any] | None = None
    tool_input: dict[str, Any] | None = None
    result_text: str = ""
    is_error: bool = False
    ctx: AgentContext | None = None


HookEvent = PreToolUseEvent | PostToolUseEvent
