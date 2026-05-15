"""TaskCreateTool — 建一個 background task。"""

from __future__ import annotations

from collections.abc import AsyncIterator

from pydantic import Field

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import TextEvent, ToolEvent, ToolInput
from orion_sdk.tools.task.runner import get_runner


class TaskCreateInput(ToolInput):
    subject: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2_000)
    command: str = Field(
        default="",
        description="Optional shell command. If set, the task will be auto-started.",
    )


class TaskCreateTool:
    name = "TaskCreate"
    description = (
        "Create a background task. If `command` is set, runs it asynchronously "
        "and you can poll status with TaskGet / output with TaskOutput."
    )
    input_schema = TaskCreateInput

    async def call(
        self,
        input: TaskCreateInput,
        ctx: AgentContext,  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        runner = get_runner()
        rec = await runner.create(
            subject=input.subject,
            description=input.description,
            command=input.command,
        )
        if input.command:
            await runner.start(rec.id)
        yield TextEvent(text=f"task created — id={rec.id}, state={rec.state}")

    def is_concurrency_safe(self, input: TaskCreateInput) -> bool:  # noqa: ARG002
        return False

    def is_read_only(self, input: TaskCreateInput) -> bool:  # noqa: ARG002
        return False

    def max_result_size_chars(self) -> int | float:
        return 500
