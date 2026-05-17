"""LoopCreateTool — 在當前對話內定期 re-fire 一段 prompt。

跟 ScheduleCreateTool 的差別:
- Loop 綁定**當前 session**,fire 時把 prompt 送回同一個對話(context 累積)
- Schedule 每次 fire 開**新 session**,獨立執行

實際 DB / scheduler 共用 cowork_schedules 表;差別在 fire path 看
target_session_id 欄是否有值。LoopCreate 自動把當前 session_id 補進
callback,user / LLM 不必傳。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Awaitable, Callable

from pydantic import Field

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput

LoopCreateCallback = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class LoopCreateInput(ToolInput):
    name: str = Field(..., min_length=1, max_length=100, description="Loop 顯示名稱")
    cron_expr: str = Field(
        ...,
        description=(
            "5-field cron 表達式。範例:'*/5 * * * *' 每 5 分鐘;"
            "'0 */2 * * *' 每 2 小時;'0 9 * * 1-5' 平日 09:00。"
            "LLM 應自己把使用者的「每 N 分鐘」翻成 cron 後再呼此 tool。"
        ),
    )
    prompt: str = Field(
        ...,
        min_length=1,
        description=(
            "每次 fire 要送回**本對話**的 prompt 內容(可含 slash command)。"
            "Slash 字面送進去由前端自己解析。"
        ),
    )


class LoopCreateTool:
    name = "LoopCreate"
    description = (
        "Schedule a recurring prompt that fires back into THIS conversation. "
        "Unlike ScheduleCreate(which opens a new session each fire), Loop appends "
        "to the current session — context accumulates across fires. Use when the "
        "user says things like 'check the deploy every 10m' or '/loop 5m /babysit-prs'. "
        "Convert natural-language intervals into a 5-field cron expression yourself "
        "before calling."
    )
    input_schema = LoopCreateInput

    def __init__(self, callback: LoopCreateCallback | None = None) -> None:
        self._callback = callback

    async def call(
        self,
        input: LoopCreateInput,
        ctx: AgentContext,
    ) -> AsyncIterator[ToolEvent]:
        if self._callback is None:
            yield ErrorEvent(
                message="LoopCreate not wired — host application did not provide a backend callback."
            )
            return
        params: dict[str, Any] = {
            "name": input.name,
            "cron_expr": input.cron_expr,
            "prompt": input.prompt,
            # callback 一律從 ctx.session_id 取當前對話,不接受 user input 防誤綁
            "target_session_id": str(ctx.session_id),
        }
        try:
            result = await self._callback(params)
        except ValueError as e:
            yield ErrorEvent(message=str(e))
            return
        except Exception as e:  # noqa: BLE001
            yield ErrorEvent(message=f"loop create failed: {type(e).__name__}: {e}")
            return
        summary = {
            "id": (result or {}).get("schedule", {}).get("id") or (result or {}).get("id"),
            "name": input.name,
            "cron_expr": input.cron_expr,
            "binds_to": "current conversation",
            "next_run_at": (result or {}).get("schedule", {}).get("next_run_at")
            or (result or {}).get("next_run_at"),
        }
        yield TextEvent(text=json.dumps(summary, indent=2, ensure_ascii=False))

    def is_concurrency_safe(self, input: LoopCreateInput) -> bool:  # noqa: ARG002
        return False

    def is_read_only(self, input: LoopCreateInput) -> bool:  # noqa: ARG002
        return False

    def max_result_size_chars(self) -> int | float:
        return 2_000
