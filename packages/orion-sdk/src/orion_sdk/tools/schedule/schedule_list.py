"""ScheduleListTool — 列現有排程。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Awaitable, Callable

from pydantic import Field

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput

ScheduleListCallback = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class ScheduleListInput(ToolInput):
    scope: str = Field(
        default="all",
        description="'user'、'project'、或 'all'(預設)。",
    )


class ScheduleListTool:
    name = "ScheduleList"
    description = (
        "List existing scheduled tasks (created via ScheduleCreate). "
        "Optionally filter by scope ('user' / 'project' / 'all')."
    )
    input_schema = ScheduleListInput

    def __init__(self, callback: ScheduleListCallback | None = None) -> None:
        self._callback = callback

    async def call(
        self,
        input: ScheduleListInput,
        ctx: AgentContext,  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        if self._callback is None:
            yield ErrorEvent(message="ScheduleList not wired by host application.")
            return
        scope = input.scope if input.scope in ("user", "project", "all") else "all"
        try:
            result = await self._callback({"scope": scope})
        except Exception as e:  # noqa: BLE001
            yield ErrorEvent(message=f"schedule list failed: {e}")
            return
        items = (result or {}).get("schedules") or []
        if not items:
            yield TextEvent(text="(no schedules)")
            return
        compact = [
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "cron_expr": s.get("cron_expr"),
                "trigger_type": s.get("trigger_type"),
                "payload": s.get("payload"),
                "scope": s.get("scope"),
                "enabled": s.get("enabled"),
                "next_run_at": s.get("next_run_at"),
                "last_run_status": s.get("last_run_status"),
            }
            for s in items
        ]
        yield TextEvent(text=json.dumps(compact, indent=2, ensure_ascii=False))

    def is_concurrency_safe(self, input: ScheduleListInput) -> bool:  # noqa: ARG002
        return True

    def is_read_only(self, input: ScheduleListInput) -> bool:  # noqa: ARG002
        return True

    def max_result_size_chars(self) -> int | float:
        return 50_000
