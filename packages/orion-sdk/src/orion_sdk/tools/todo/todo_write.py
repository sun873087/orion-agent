"""TodoWriteTool — agent 內部 todo list,存在 ctx.todos。

對應 TS Claude Code TodoWrite。模型用這個工具自我規劃多步驟任務。

Phase 1:in-memory(存 ctx),conversation 結束就消失。Phase 2 會持久化。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal

from pydantic import BaseModel, Field

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput

TodoStatus = Literal["pending", "in_progress", "completed"]


class TodoItem(BaseModel):
    """單一 todo。"""

    content: str = Field(..., description="The task description.")
    status: TodoStatus = Field(default="pending", description="pending / in_progress / completed")


class TodoWriteInput(ToolInput):
    """TodoWriteTool 的 input。**整個** todo list 會被覆寫(不是 append)。"""

    todos: list[TodoItem] = Field(
        ...,
        description=(
            "The complete todo list (replaces existing). "
            "Each item has 'content' and 'status' (pending/in_progress/completed). "
            "Keep exactly one item in_progress at a time."
        ),
    )


class TodoWriteTool:
    name = "TodoWrite"
    description = (
        "Manage your task list. Pass the complete updated list each call (it replaces "
        "the existing one, not append). Keep exactly one item in_progress at a time. "
        "Use this for multi-step tasks to track progress visibly."
    )
    input_schema = TodoWriteInput

    async def call(
        self,
        input: TodoWriteInput,
        ctx: AgentContext,
    ) -> AsyncIterator[ToolEvent]:
        in_progress_count = sum(1 for t in input.todos if t.status == "in_progress")
        if in_progress_count > 1:
            yield ErrorEvent(
                message=f"At most one todo may be in_progress at a time (got {in_progress_count})."
            )
            return

        # 覆寫 ctx.todos
        ctx.todos = [{"content": t.content, "status": t.status} for t in input.todos]

        # 摘要回給模型看(它就知道現況)
        if not ctx.todos:
            yield TextEvent(text="(todo list cleared)")
            return

        lines = ["Updated todo list:"]
        symbol = {"pending": "○", "in_progress": "◐", "completed": "●"}
        for i, t in enumerate(ctx.todos, 1):
            lines.append(f"  {symbol.get(t['status'], '?')} {i}. {t['content']}  [{t['status']}]")
        yield TextEvent(text="\n".join(lines))

    def is_concurrency_safe(self, input: TodoWriteInput) -> bool:  # noqa: ARG002
        return False  # 寫 ctx.todos,順序重要

    def is_read_only(self, input: TodoWriteInput) -> bool:  # noqa: ARG002
        return False

    def max_result_size_chars(self) -> int | float:
        return 5_000
