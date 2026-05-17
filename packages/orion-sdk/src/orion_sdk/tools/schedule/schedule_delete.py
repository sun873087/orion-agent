"""ScheduleDeleteTool — 刪一筆排程。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Awaitable, Callable

from pydantic import Field

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput

ScheduleDeleteCallback = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class ScheduleDeleteInput(ToolInput):
    id: str = Field(..., min_length=1, description="排程 id(從 ScheduleList 取得)")


class ScheduleDeleteTool:
    name = "ScheduleDelete"
    description = (
        "Delete a scheduled task by its id. "
        "Use ScheduleList first to look up the id."
    )
    input_schema = ScheduleDeleteInput

    def __init__(self, callback: ScheduleDeleteCallback | None = None) -> None:
        self._callback = callback

    async def call(
        self,
        input: ScheduleDeleteInput,
        ctx: AgentContext,  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        if self._callback is None:
            yield ErrorEvent(message="ScheduleDelete not wired by host application.")
            return
        try:
            await self._callback({"id": input.id})
        except ValueError as e:
            yield ErrorEvent(message=str(e))
            return
        except Exception as e:  # noqa: BLE001
            yield ErrorEvent(message=f"schedule delete failed: {e}")
            return
        yield TextEvent(text=f"schedule {input.id} deleted")

    def is_concurrency_safe(self, input: ScheduleDeleteInput) -> bool:  # noqa: ARG002
        return False

    def is_read_only(self, input: ScheduleDeleteInput) -> bool:  # noqa: ARG002
        return False

    def max_result_size_chars(self) -> int | float:
        return 200
