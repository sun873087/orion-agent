"""WebSocket-based CanUseToolFn — 把 Phase 1 permission 接到 ws round-trip。

對應 spec § 5 ws_permissions.py。

流程:
  1. query_loop 內 run_one_tool 呼 can_use_tool(tool, input, ctx)
  2. 我們的 callback:
     - 若 tool.is_read_only(input)=True → 直接 allow(避免每次問)
     - 否則:
         * 產 request_id UUID
         * 推 PermissionAskEvent 到 outbound_queue
         * 記 future = pending[request_id]
         * await future(timeout 60s)
         * timeout → DENY
         * 收到 PermissionDecisionEvent(在 reader_task 內 set future)→ 套用

Reader task 收到 PermissionDecisionEvent 時,呼 `resolve_decision(request_id, decision)`
把 future set。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from orion_agent.api.event_schema import (
    PermissionAskEvent,
)
from orion_agent.core.state import AgentContext
from orion_agent.core.tool import Tool
from orion_agent.permissions.decisions import (
    CanUseToolFn,
    PermissionDecision,
    PermissionResult,
)

PERMISSION_TIMEOUT_S = 60


@dataclass
class PendingPermissions:
    """state shared between can_use_tool callback + ws reader task。"""

    pending: dict[str, asyncio.Future[str]] = field(default_factory=dict)
    """request_id → Future[decision_str]。"""

    def resolve(self, request_id: str, decision: str) -> None:
        """ws reader 收到 PermissionDecisionEvent 時呼,把 future set 起來。"""
        fut = self.pending.pop(request_id, None)
        if fut is None or fut.done():
            return  # silently drop(timeout 後到達 / 重複 / unknown)
        fut.set_result(decision)


def make_can_use_tool_for_websocket(
    *,
    outbound_queue: asyncio.Queue[Any],
    pending: PendingPermissions,
    timeout_s: int = PERMISSION_TIMEOUT_S,
) -> CanUseToolFn:
    """工廠:產符合 CanUseToolFn Protocol 的 callable。

    callable 從 outbound_queue 推 PermissionAskEvent;ws writer task 會 ws.send 出去。
    """

    async def can_use_tool(
        tool: Tool[Any],
        tool_input: dict[str, Any],
        ctx: AgentContext,  # noqa: ARG001
    ) -> PermissionResult:
        # Read-only 工具直接 allow
        try:
            parsed = tool.input_schema.model_validate(tool_input)
            if tool.is_read_only(parsed):
                return PermissionResult(decision=PermissionDecision.ALLOW)
        except Exception:  # noqa: BLE001 — parse 失敗保守問 user
            pass

        request_id = uuid4().hex
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()
        pending.pending[request_id] = fut

        ask = PermissionAskEvent(
            request_id=request_id,
            tool_name=tool.name,
            input=tool_input,
            timeout_seconds=timeout_s,
        )
        # outbound 是 anyio.MemoryObjectSendStream → .send();
        # 也支援 asyncio.Queue → .put()。動態判斷。
        if hasattr(outbound_queue, "send"):
            await outbound_queue.send(ask)
        else:
            await outbound_queue.put(ask)

        try:
            decision_str = await asyncio.wait_for(fut, timeout=timeout_s)
        except TimeoutError:
            pending.pending.pop(request_id, None)
            return PermissionResult(
                decision=PermissionDecision.DENY,
                reason=f"user did not respond within {timeout_s}s",
            )

        if decision_str in ("allow", "always_allow"):
            return PermissionResult(decision=PermissionDecision.ALLOW)
        return PermissionResult(
            decision=PermissionDecision.DENY,
            reason="user denied",
        )

    return can_use_tool
