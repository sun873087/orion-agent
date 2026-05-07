"""TaskOutputTool — 拿 task 的最近 stdout 行。"""

from __future__ import annotations

from collections.abc import AsyncIterator

from pydantic import Field

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput
from orion_agent.tools.task.runner import get_runner


class TaskOutputInput(ToolInput):
    task_id: str = Field(...)
    max_lines: int = Field(default=200, ge=1, le=2000)


class TaskOutputTool:
    name = "TaskOutput"
    description = "Read the recent stdout/stderr lines from a background task."
    input_schema = TaskOutputInput

    async def call(
        self,
        input: TaskOutputInput,
        ctx: AgentContext,  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        runner = get_runner()
        rec = runner.get(input.task_id)
        if rec is None:
            yield ErrorEvent(message=f"task not found: {input.task_id}")
            return
        lines = runner.output(input.task_id, max_lines=input.max_lines)
        if not lines:
            yield TextEvent(text=f"(no output yet — state={rec.state})")
            return
        yield TextEvent(text="\n".join(lines))

    def is_concurrency_safe(self, input: TaskOutputInput) -> bool:  # noqa: ARG002
        return True

    def is_read_only(self, input: TaskOutputInput) -> bool:  # noqa: ARG002
        return True

    def max_result_size_chars(self) -> int | float:
        return 50_000
