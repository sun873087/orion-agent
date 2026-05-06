"""StreamingToolExecutor — 模型 yield 一個 tool_use 立刻開始跑(不等整輪 stream 結束)。

對應 TS Claude Code `src/services/tools/StreamingToolExecutor.ts`。

vs `tool_orchestration.run_tools`(批次模式):
  ─ run_tools  等模型 yield 完所有 tool_use 才開始
  ─ StreamingToolExecutor 邊 yield 邊跑

關鍵 invariant:
  ─ 已執行中的工具全部 concurrency-safe + 新工具也 safe → 加入並發
  ─ 否則 non-safe 工具等到全部跑完才開始,且會擋住後續工具
  ─ 結果 yield 順序 = add_tool 順序(不是完成順序)

使用方式:

    async with StreamingToolExecutor(...) as executor:
        async for ev in provider.stream(...):
            if isinstance(ev, ToolUseStopEvent):
                executor.add_tool(tool_use_block)
        # stream done → drain
        async for upd in executor.drain():
            yield upd
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import Tool
from orion_agent.core.tool_execution import (
    ToolUpdate,
    run_one_tool,
)
from orion_agent.hooks.registry import HookRegistry
from orion_agent.llm.types import ToolUseBlock
from orion_agent.permissions.decisions import CanUseToolFn

ToolStatus = Literal["queued", "executing", "done"]


@dataclass
class TrackedTool:
    """單一 tool 在 executor 裡的狀態。"""

    block: ToolUseBlock
    is_concurrency_safe: bool
    status: ToolStatus = "queued"
    send_stream: MemoryObjectSendStream[ToolUpdate] | None = None
    recv_stream: MemoryObjectReceiveStream[ToolUpdate] | None = None
    buffered_updates: list[ToolUpdate] = field(default_factory=list)


class StreamingToolExecutor:
    """串流模式工具執行器。"""

    def __init__(
        self,
        tools: list[Tool[Any]],
        *,
        can_use_tool: CanUseToolFn,
        hooks: HookRegistry,
        ctx: AgentContext,
    ) -> None:
        self.tools_by_name: dict[str, Tool[Any]] = {t.name: t for t in tools}
        self.can_use_tool = can_use_tool
        self.hooks = hooks
        self.ctx = ctx
        self.tracked: list[TrackedTool] = []
        self._task_group: anyio.abc.TaskGroup | None = None
        self._task_group_cm: Any = None

    async def __aenter__(self) -> StreamingToolExecutor:
        self._task_group_cm = anyio.create_task_group()
        self._task_group = await self._task_group_cm.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> bool | None:
        # 確保所有未啟動的 queued 工具被啟動,executor 收尾
        self._maybe_start_more()
        if self._task_group_cm is None:
            return None
        return await self._task_group_cm.__aexit__(*args)  # type: ignore[no-any-return]

    def add_tool(self, block: ToolUseBlock) -> None:
        """收到模型新 tool_use 就 call 一次。可能立刻開跑也可能 queue。"""
        tool = self.tools_by_name.get(block.name)
        is_safe = False
        if tool is not None:
            try:
                parsed = tool.input_schema.model_validate(block.input)
                is_safe = tool.is_concurrency_safe(parsed)
            except Exception:  # noqa: BLE001
                is_safe = False

        send, recv = anyio.create_memory_object_stream[ToolUpdate](max_buffer_size=64)
        tt = TrackedTool(
            block=block,
            is_concurrency_safe=is_safe,
            send_stream=send,
            recv_stream=recv,
        )
        self.tracked.append(tt)
        self._maybe_start_more()

    def _can_execute(self, candidate_safe: bool) -> bool:
        """判斷新工具能否立刻開跑。對應 TS canExecuteTool。"""
        executing = [t for t in self.tracked if t.status == "executing"]
        if not executing:
            return True
        return candidate_safe and all(t.is_concurrency_safe for t in executing)

    def _maybe_start_more(self) -> None:
        """掃 queue,該開的開,non-safe 擋住後續。"""
        if self._task_group is None:
            return
        for tt in self.tracked:
            if tt.status != "queued":
                continue
            if not self._can_execute(tt.is_concurrency_safe):
                break  # 擋住後續所有 queued
            tt.status = "executing"
            self._task_group.start_soon(self._run_tool, tt)

    async def _run_tool(self, tt: TrackedTool) -> None:
        """背景 task:跑單一工具,把每個 update 推進 send_stream。"""
        if tt.send_stream is None:
            return
        try:
            async for upd in run_one_tool(
                tt.block.id,
                tt.block.name,
                tt.block.input,
                tools_by_name=self.tools_by_name,
                can_use_tool=self.can_use_tool,
                hooks=self.hooks,
                ctx=self.ctx,
            ):
                await tt.send_stream.send(upd)
        finally:
            await tt.send_stream.aclose()
            tt.status = "done"
            self._maybe_start_more()

    async def drain(self) -> AsyncIterator[ToolUpdate]:
        """順序 yield 所有 tool 的 updates(按 add 順序,不是完成順序)。

        在 stream 結束後 call 一次。會 await 每個 tool 完成才前進到下一個。
        """
        for tt in self.tracked:
            if tt.recv_stream is None:
                continue
            async with tt.recv_stream:
                async for upd in tt.recv_stream:
                    yield upd
