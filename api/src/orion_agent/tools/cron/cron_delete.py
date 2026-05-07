"""CronDeleteTool — 移除一個 cron job。"""

from __future__ import annotations

from collections.abc import AsyncIterator

from pydantic import Field

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput
from orion_agent.tools.cron.scheduler import get_scheduler


class CronDeleteInput(ToolInput):
    job_id: str = Field(...)


class CronDeleteTool:
    name = "CronDelete"
    description = "Delete a cron job by its id."
    input_schema = CronDeleteInput

    async def call(
        self,
        input: CronDeleteInput,
        ctx: AgentContext,  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        ok = get_scheduler().delete(input.job_id)
        if not ok:
            yield ErrorEvent(message=f"cron job not found: {input.job_id}")
            return
        yield TextEvent(text=f"deleted cron job {input.job_id}")

    def is_concurrency_safe(self, input: CronDeleteInput) -> bool:  # noqa: ARG002
        return False

    def is_read_only(self, input: CronDeleteInput) -> bool:  # noqa: ARG002
        return False

    def max_result_size_chars(self) -> int | float:
        return 200
