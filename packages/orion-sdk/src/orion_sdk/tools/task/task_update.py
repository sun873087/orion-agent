"""TaskUpdateTool — 改 task 狀態 / metadata。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Literal

from pydantic import Field

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput
from orion_sdk.tools.task.runner import get_runner


class TaskUpdateInput(ToolInput):
    task_id: str = Field(...)
    state: Literal[
        "pending", "in_progress", "completed", "failed", "stopped", "deleted", "",
    ] = Field(default="", description="New state. Empty = unchanged.")
    subject: str = Field(default="")
    description: str = Field(default="")
    metadata_json: str = Field(
        default="",
        description="JSON-encoded dict to merge into metadata.",
    )


class TaskUpdateTool:
    name = "TaskUpdate"
    description = "Update task state / subject / description / metadata."
    input_schema = TaskUpdateInput

    async def call(
        self,
        input: TaskUpdateInput,
        ctx: AgentContext,  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        meta_patch = None
        if input.metadata_json:
            try:
                meta_patch = json.loads(input.metadata_json)
            except json.JSONDecodeError as e:
                yield ErrorEvent(message=f"invalid metadata_json: {e}")
                return
            if not isinstance(meta_patch, dict):
                yield ErrorEvent(message="metadata_json must decode to an object")
                return

        runner = get_runner()
        rec = await runner.update(
            input.task_id,
            state=(input.state or None),
            subject=(input.subject or None),
            description=(input.description or None),
            metadata_patch=meta_patch,
        )
        if rec is None:
            yield ErrorEvent(message=f"task not found: {input.task_id}")
            return
        yield TextEvent(text=json.dumps(rec.to_summary(), indent=2))

    def is_concurrency_safe(self, input: TaskUpdateInput) -> bool:  # noqa: ARG002
        return False

    def is_read_only(self, input: TaskUpdateInput) -> bool:  # noqa: ARG002
        return False

    def max_result_size_chars(self) -> int | float:
        return 5_000
