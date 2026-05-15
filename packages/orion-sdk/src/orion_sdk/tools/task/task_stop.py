"""TaskStopTool — cancel 跑中的 task。"""

from __future__ import annotations

from collections.abc import AsyncIterator

from pydantic import Field

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput
from orion_sdk.tools.task.runner import get_runner


class TaskStopInput(ToolInput):
    task_id: str = Field(...)


class TaskStopTool:
    name = "TaskStop"
    description = "Stop / cancel a running background task by id."
    input_schema = TaskStopInput

    async def call(
        self,
        input: TaskStopInput,
        ctx: AgentContext,  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        runner = get_runner()
        ok = await runner.stop(input.task_id)
        if not ok:
            yield ErrorEvent(message=f"task not found: {input.task_id}")
            return
        rec = runner.get(input.task_id)
        state = rec.state if rec else "?"
        yield TextEvent(text=f"task {input.task_id} → state={state}")

    def is_concurrency_safe(self, input: TaskStopInput) -> bool:  # noqa: ARG002
        return False

    def is_read_only(self, input: TaskStopInput) -> bool:  # noqa: ARG002
        return False

    def max_result_size_chars(self) -> int | float:
        return 500
