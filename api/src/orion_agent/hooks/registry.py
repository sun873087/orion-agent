"""HookRegistry — 集中註冊 / 派發 hook callback。

Phase 1:`register / dispatch / pre_tool_use / post_tool_use`(in-process callbacks)。
Phase 8 擴充:
- `fire(event)`:回傳 list[result],含 exception 不擋
- `fire_pre_tool_use(event)`:聚合 abort / modified_input
- `fire_user_prompt_submit(event)`:聚合 abort / additional_context
- `unregister(event_type, callback)`:刪 handler
- 8 種 event 都走同一 dispatch,event.type 字串對應 HookEventName
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from orion_agent.hooks.events import (
    HookEvent,
    PostToolUseEvent,
    PreToolUseEvent,
    PreToolUseResult,
    UserPromptSubmitEvent,
    UserPromptSubmitResult,
)

logger = logging.getLogger(__name__)


HookCallback = Callable[[HookEvent], Awaitable[Any]]
"""Hook callback。回值依 event:
- PreToolUse:回 False / PreToolUseResult / None
- UserPromptSubmit:回 UserPromptSubmitResult / None
- 其他:None(忽略)
"""


class HookRegistry:
    """管理已註冊的 hook callbacks。"""

    def __init__(self) -> None:
        self._hooks: dict[str, list[HookCallback]] = defaultdict(list)

    def register(self, event_type: str, callback: HookCallback) -> None:
        """註冊一個 callback 給指定 event_type。"""
        self._hooks[event_type].append(callback)

    def unregister(self, event_type: str, callback: HookCallback) -> bool:
        """移除單一 callback。Returns True 若有移除。"""
        bucket = self._hooks.get(event_type)
        if not bucket:
            return False
        try:
            bucket.remove(callback)
        except ValueError:
            return False
        return True

    def clear(self) -> None:
        """清空全部 hooks(主要給測試用)。"""
        self._hooks.clear()

    def count(self, event_type: str) -> int:
        return len(self._hooks.get(event_type, []))

    # ─── Phase 1 API(向後相容)──────────────────────────────────────────

    async def dispatch(self, event: HookEvent) -> bool:
        """派發 event 給所有註冊的 callback。

        Returns:
            True = 全部放行 / 沒 hook 攔
            False = 至少一個 PreToolUse hook 回 False(視同 permission deny)
        """
        callbacks = self._hooks.get(event.type, [])
        all_allowed = True
        for cb in callbacks:
            try:
                result = await cb(event)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "hook handler raised %s on %s: %s",
                    type(e).__name__,
                    event.type,
                    e,
                )
                continue
            if result is False and isinstance(event, PreToolUseEvent) or (
                isinstance(result, PreToolUseResult)
                and result.abort
                and isinstance(event, PreToolUseEvent)
            ):
                all_allowed = False
        return all_allowed

    async def pre_tool_use(self, event: PreToolUseEvent) -> bool:
        """便利 wrapper(query_loop 用)。"""
        return await self.dispatch(event)

    async def post_tool_use(self, event: PostToolUseEvent) -> None:
        """便利 wrapper(query_loop 用,回值忽略)。"""
        await self.dispatch(event)

    # ─── Phase 8 API(新)─────────────────────────────────────────────────

    async def fire(self, event: HookEvent) -> list[Any]:
        """觸發所有 handler,回 list[result]。handler 例外不影響 caller。"""
        callbacks = self._hooks.get(event.type, [])
        out: list[Any] = []
        for cb in callbacks:
            try:
                out.append(await cb(event))
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "hook handler raised %s on %s: %s",
                    type(e).__name__,
                    event.type,
                    e,
                )
                out.append(None)
        return out

    async def fire_pre_tool_use(
        self, event: PreToolUseEvent,
    ) -> PreToolUseResult:
        """聚合多 PreToolUse hook 結果。

        - 任一 abort → 整體 abort(reason 取第一個)
        - modified_input:多 hook 都改 → 後者 wins
        """
        results = await self.fire(event)

        first_abort: PreToolUseResult | None = None
        last_modified: dict[str, Any] | None = None

        for r in results:
            if r is False:
                if first_abort is None:
                    first_abort = PreToolUseResult(
                        abort=True, abort_reason="pre_tool_use returned False",
                    )
            elif isinstance(r, PreToolUseResult):
                if r.abort and first_abort is None:
                    first_abort = r
                if r.modified_input is not None:
                    last_modified = r.modified_input

        if first_abort is not None:
            return first_abort
        return PreToolUseResult(abort=False, modified_input=last_modified)

    async def fire_user_prompt_submit(
        self, event: UserPromptSubmitEvent,
    ) -> UserPromptSubmitResult:
        """聚合 UserPromptSubmit。

        - 任一 abort → abort
        - additional_context:多 hook 給 → 串接(`\\n\\n` 連接)
        """
        results = await self.fire(event)

        first_abort: UserPromptSubmitResult | None = None
        contexts: list[str] = []

        for r in results:
            if isinstance(r, UserPromptSubmitResult):
                if r.abort and first_abort is None:
                    first_abort = r
                if r.additional_context:
                    contexts.append(r.additional_context)

        if first_abort is not None:
            return first_abort
        joined = "\n\n".join(contexts) if contexts else None
        return UserPromptSubmitResult(abort=False, additional_context=joined)
