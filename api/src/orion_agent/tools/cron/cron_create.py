"""CronCreateTool — 排一個 cron job。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from pydantic import Field

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput
from orion_agent.tools.cron.scheduler import get_scheduler


class CronCreateInput(ToolInput):
    name: str = Field(..., min_length=1, max_length=100)
    cron_expr: str = Field(
        ...,
        description=(
            "5-field cron expression (minute hour day month day_of_week). "
            "Example: '0 9 * * 1-5' for 09:00 weekdays."
        ),
    )
    command: str = Field(..., min_length=1, max_length=2_000)


class CronCreateTool:
    name = "CronCreate"
    description = (
        "Schedule a recurring shell command using a 5-field cron expression. "
        "Job runs in the background;list with CronList, remove with CronDelete."
    )
    input_schema = CronCreateInput

    async def call(
        self,
        input: CronCreateInput,
        ctx: AgentContext,  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        try:
            cj = get_scheduler().add(
                name=input.name,
                cron_expr=input.cron_expr,
                command=input.command,
            )
        except ValueError as e:
            yield ErrorEvent(message=str(e))
            return
        except Exception as e:  # noqa: BLE001
            yield ErrorEvent(message=f"cron add failed: {type(e).__name__}: {e}")
            return
        yield TextEvent(text=json.dumps(cj.to_summary(), indent=2))

    def is_concurrency_safe(self, input: CronCreateInput) -> bool:  # noqa: ARG002
        return False

    def is_read_only(self, input: CronCreateInput) -> bool:  # noqa: ARG002
        return False

    def max_result_size_chars(self) -> int | float:
        return 1_000
