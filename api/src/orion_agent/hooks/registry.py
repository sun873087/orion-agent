"""HookRegistry — 集中註冊 / 派發 hook callback。

Phase 1 介面:`register(event_type, callback)` + `dispatch(event)`。
單向 — hook 不回值(PreToolUse 例外:回 False 視同 deny)。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable

from orion_agent.hooks.events import HookEvent, PostToolUseEvent, PreToolUseEvent

HookCallback = Callable[[HookEvent], Awaitable[bool | None]]
"""Hook callback signature。回 False = pre_tool_use 阻擋;其他 → 放行。"""


class HookRegistry:
    """管理已註冊的 hook callbacks。"""

    def __init__(self) -> None:
        self._hooks: dict[str, list[HookCallback]] = defaultdict(list)

    def register(self, event_type: str, callback: HookCallback) -> None:
        """註冊一個 callback 給指定 event_type。"""
        self._hooks[event_type].append(callback)

    def clear(self) -> None:
        """清空全部 hooks(主要給測試用)。"""
        self._hooks.clear()

    async def dispatch(self, event: HookEvent) -> bool:
        """派發 event 給所有註冊的 callback。

        Returns:
            True = 全部放行 / 沒 hook 攔
            False = 至少一個 PreToolUseEvent hook 回 False(視同 permission deny)
        """
        callbacks = self._hooks.get(event.type, [])
        all_allowed = True
        for cb in callbacks:
            result = await cb(event)
            if result is False and isinstance(event, PreToolUseEvent):
                all_allowed = False
        return all_allowed

    async def pre_tool_use(
        self,
        event: PreToolUseEvent,
    ) -> bool:
        """便利 wrapper — query_loop 直接 call 這個。"""
        return await self.dispatch(event)

    async def post_tool_use(
        self,
        event: PostToolUseEvent,
    ) -> None:
        """便利 wrapper(回值忽略)。"""
        await self.dispatch(event)
