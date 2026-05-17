"""ScheduleCreateTool — 建立一筆排程任務。

跟 CronCreateTool 不同:這個排「對話任務」(觸發開新 session 跑 LLM),
不排 shell command。

CRUD 由 sidecar 透過 callback 注入(SDK 不直接動 DB)。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Awaitable, Callable

from pydantic import Field

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput

ScheduleCreateCallback = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class ScheduleCreateInput(ToolInput):
    name: str = Field(..., min_length=1, max_length=100, description="排程顯示名稱")
    cron_expr: str = Field(
        ...,
        description=(
            "5-field cron 表達式 (minute hour day month day_of_week)。"
            "範例:'0 8 * * *' 每天 08:00;'0 9 * * 1' 每週一 09:00;"
            "'0 10 1 * *' 每月 1 號 10:00。LLM 應自己把使用者的自然語言"
            "(如「每天早上 8 點」)翻成 cron expr 後再呼此 tool。"
        ),
    )
    trigger_type: str = Field(
        ...,
        description=(
            "觸發類型:'skill' 表示執行某個 Skill;'prompt' 表示直接送一段 prompt。"
        ),
    )
    payload: str = Field(
        ...,
        min_length=1,
        description=(
            "若 trigger_type='skill':Skill 名稱(從已安裝 Skills 內挑)。"
            "若 trigger_type='prompt':要送 LLM 的 prompt 內容。"
        ),
    )
    scope: str = Field(
        default="user",
        description=(
            "'user' 個人排程(跨所有 project 都跑);'project' 專案排程"
            "(綁當前 project)。預設 'user'。"
        ),
    )


class ScheduleCreateTool:
    name = "ScheduleCreate"
    description = (
        "Create a scheduled task that opens a new conversation at the given time. "
        "Use this when the user asks to schedule something like 'every day at 8am "
        "run the daily-news skill' or 'every Monday at 9am summarize last week's PRs'. "
        "If the user gives natural-language timing, convert it to a 5-field cron "
        "expression yourself before calling. "
        "Use trigger_type='skill' to run an existing Skill, or 'prompt' for free-form text."
    )
    input_schema = ScheduleCreateInput

    def __init__(self, callback: ScheduleCreateCallback | None = None) -> None:
        self._callback = callback

    async def call(
        self,
        input: ScheduleCreateInput,
        ctx: AgentContext,
    ) -> AsyncIterator[ToolEvent]:
        if self._callback is None:
            yield ErrorEvent(
                message="ScheduleCreate not wired — host application did not provide a backend callback."
            )
            return
        params: dict[str, Any] = {
            "name": input.name,
            "cron_expr": input.cron_expr,
            "trigger_type": input.trigger_type,
            "payload": input.payload,
            "scope": input.scope if input.scope in ("user", "project") else "user",
        }
        # Project-scope 由 caller 從 ctx 自動補 project_id(SDK 不直接接 project 概念)
        if hasattr(ctx, "project_id") and getattr(ctx, "project_id", None):
            params["project_id"] = getattr(ctx, "project_id")
        try:
            result = await self._callback(params)
        except ValueError as e:
            yield ErrorEvent(message=str(e))
            return
        except Exception as e:  # noqa: BLE001
            yield ErrorEvent(message=f"schedule create failed: {type(e).__name__}: {e}")
            return
        summary = {
            "id": (result or {}).get("schedule", {}).get("id") or (result or {}).get("id"),
            "name": input.name,
            "cron_expr": input.cron_expr,
            "trigger_type": input.trigger_type,
            "next_run_at": (result or {}).get("schedule", {}).get("next_run_at")
            or (result or {}).get("next_run_at"),
        }
        yield TextEvent(text=json.dumps(summary, indent=2, ensure_ascii=False))

    def is_concurrency_safe(self, input: ScheduleCreateInput) -> bool:  # noqa: ARG002
        return False

    def is_read_only(self, input: ScheduleCreateInput) -> bool:  # noqa: ARG002
        return False

    def max_result_size_chars(self) -> int | float:
        return 2_000
