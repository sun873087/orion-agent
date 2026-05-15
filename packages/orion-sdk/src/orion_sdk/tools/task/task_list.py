"""TaskListTool — 列出 tasks(可選 state / subject 過濾)。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Literal

from pydantic import Field

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import TextEvent, ToolEvent, ToolInput
from orion_sdk.tools.task.runner import TaskState, get_runner


class TaskListInput(ToolInput):
    state: Literal[
        "pending", "in_progress", "completed", "failed", "stopped", "deleted", "",
    ] = Field(
        default="",
        description="Filter by state. Empty = all.",
    )
    subject_contains: str = Field(default="", description="Substring filter on subject.")
    max_results: int = Field(default=20, ge=1, le=100)


class TaskListTool:
    name = "TaskList"
    description = "List background tasks, optionally filtered by state / subject."
    input_schema = TaskListInput

    async def call(
        self,
        input: TaskListInput,
        ctx: AgentContext,  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        runner = get_runner()
        state: TaskState | None = input.state if input.state else None
        records = runner.list_tasks(
            state=state,
            subject_contains=input.subject_contains or None,
        )[: input.max_results]
        if not records:
            yield TextEvent(text="(no tasks)")
            return
        out = [r.to_summary() for r in records]
        yield TextEvent(text=json.dumps(out, indent=2))

    def is_concurrency_safe(self, input: TaskListInput) -> bool:  # noqa: ARG002
        return True

    def is_read_only(self, input: TaskListInput) -> bool:  # noqa: ARG002
        return True

    def max_result_size_chars(self) -> int | float:
        return 30_000
