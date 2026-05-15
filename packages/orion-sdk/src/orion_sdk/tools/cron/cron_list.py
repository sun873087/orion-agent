"""CronListTool — 列已排程 cron jobs。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import TextEvent, ToolEvent, ToolInput
from orion_sdk.tools.cron.scheduler import get_scheduler


class CronListInput(ToolInput):
    """No params."""


class CronListTool:
    name = "CronList"
    description = "List all scheduled cron jobs."
    input_schema = CronListInput

    async def call(
        self,
        input: CronListInput,  # noqa: ARG002
        ctx: AgentContext,  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        jobs = get_scheduler().list()
        if not jobs:
            yield TextEvent(text="(no cron jobs)")
            return
        out = [j.to_summary() for j in jobs]
        yield TextEvent(text=json.dumps(out, indent=2))

    def is_concurrency_safe(self, input: CronListInput) -> bool:  # noqa: ARG002
        return True

    def is_read_only(self, input: CronListInput) -> bool:  # noqa: ARG002
        return True

    def max_result_size_chars(self) -> int | float:
        return 30_000
