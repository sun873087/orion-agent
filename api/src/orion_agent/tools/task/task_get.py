"""TaskGetTool — 取單一 task 狀態。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from pydantic import Field

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput
from orion_agent.tools.task.runner import get_runner


class TaskGetInput(ToolInput):
    task_id: str = Field(...)


class TaskGetTool:
    name = "TaskGet"
    description = "Get the status / metadata of a background task by id."
    input_schema = TaskGetInput

    async def call(
        self,
        input: TaskGetInput,
        ctx: AgentContext,  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        runner = get_runner()
        rec = runner.get(input.task_id)
        if rec is None:
            yield ErrorEvent(message=f"task not found: {input.task_id}")
            return
        yield TextEvent(text=json.dumps(rec.to_summary(), indent=2))

    def is_concurrency_safe(self, input: TaskGetInput) -> bool:  # noqa: ARG002
        return True

    def is_read_only(self, input: TaskGetInput) -> bool:  # noqa: ARG002
        return True

    def max_result_size_chars(self) -> int | float:
        return 5_000
