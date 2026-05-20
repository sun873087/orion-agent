"""三態 permission 決策 + CanUseToolFn callback Protocol。

對應 TS Claude Code `src/permissions/`。範圍只有三態與 callback,
完整 policy(deny rules / allow rules / persisted decisions)是 / 8 的事。
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from orion_sdk.core.state import AgentContext
    from orion_sdk.core.tool import Tool


# Tool execution 在 call can_use_tool 前 set 這個 var,讓 callback 取得
# 對應的 tool_use_id(否則 Protocol 簽名沒有,沒辦法把 approval reply 對回去)。
# 用 contextvar 而非加 Protocol arg,避免散布 signature change 到所有
# CanUseToolFn 實作 / 測試。Default None — sync caller / 不在 tool exec 內讀
# 都安全。
current_tool_use_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "orion_sdk_current_tool_use_id", default=None,
)


class PermissionDecision(StrEnum):
    """三態決策。"""

    ALLOW = "allow"
    """允許執行。"""

    ASK = "ask"
    """需要互動詢問 user 範圍內視同 deny(沒有 UI 可詢問)。"""

    DENY = "deny"
    """拒絕執行 — query_loop 會回 synthetic ToolResultBlock(is_error=True)給模型。"""


@dataclass
class PermissionResult:
    """CanUseToolFn 的回傳值。"""

    decision: PermissionDecision
    reason: str = ""
    """給 user / model 看的解釋(deny 時必填)。"""


class CanUseToolFn(Protocol):
    """Permission callback。query_loop 在每次 tool call 前呼叫。

    對應 TS `CanUseToolFn`。實作可以靜態(always_allow)、policy-based(白名單),
    或互動式(FastAPI 透過 WebSocket 問前端)。
    """

    async def __call__(
        self,
        tool: Tool[Any],
        tool_input: dict[str, Any],
        ctx: AgentContext,
    ) -> PermissionResult:
        ...


async def always_allow(
    tool: Tool[Any], # noqa: ARG001
    tool_input: dict[str, Any], # noqa: ARG001
    ctx: AgentContext, # noqa: ARG001
) -> PermissionResult:
    """預設:全部允許。Dev / 測試用,production 應換成有 policy 的實作。"""
    return PermissionResult(decision=PermissionDecision.ALLOW)


async def always_deny(
    tool: Tool[Any], # noqa: ARG001
    tool_input: dict[str, Any], # noqa: ARG001
    ctx: AgentContext, # noqa: ARG001
) -> PermissionResult:
    """全拒。測試用。"""
    return PermissionResult(
        decision=PermissionDecision.DENY,
        reason="always_deny policy is active",
    )
