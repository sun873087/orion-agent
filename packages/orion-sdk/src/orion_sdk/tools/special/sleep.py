"""SleepTool。對應 TS SleepTool。

autonomous agent 主動延遲下一輪用(例:輪詢狀態時不要 spin)。

範圍 [60, 3600] 秒(1 分–1 小時),由 query_loop / runtime 視情境用 ctx.abort_event
判斷可否中斷。本工具呼叫 anyio.sleep,被 abort 時會立即中斷。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import anyio
from pydantic import Field

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput

_MIN_SLEEP_SECS = 60
_MAX_SLEEP_SECS = 3600


class SleepInput(ToolInput):
    seconds: float = Field(
        ...,
        ge=_MIN_SLEEP_SECS,
        le=_MAX_SLEEP_SECS,
        description=(
            f"How long to sleep, in seconds. Clamped to [{_MIN_SLEEP_SECS}, "
            f"{_MAX_SLEEP_SECS}]. Use for autonomous polling — sleep before "
            "checking back."
        ),
    )
    reason: str = Field(
        default="",
        description="Short reason shown in telemetry (e.g. 'waiting for build').",
    )


class SleepTool:
    name = "Sleep"
    description = (
        "Sleep for a specified duration before continuing. "
        "Use in autonomous loops to avoid busy-waiting."
    )
    input_schema = SleepInput

    async def call(
        self,
        input: SleepInput,
        ctx: AgentContext,
    ) -> AsyncIterator[ToolEvent]:
        seconds = max(_MIN_SLEEP_SECS, min(_MAX_SLEEP_SECS, float(input.seconds)))
        try:
            with anyio.move_on_after(seconds) as scope:
                await ctx.abort_event.wait()
        except Exception as e: # noqa: BLE001
            yield ErrorEvent(message=f"sleep failed: {e}")
            return

        if not scope.cancel_called and ctx.abort_event.is_set():
            yield TextEvent(text="sleep interrupted by abort after partial wait")
        else:
            yield TextEvent(
                text=(
                    f"slept for {seconds:.0f}s"
                    + (f" — {input.reason}" if input.reason else "")
                ),
            )

    def is_concurrency_safe(self, input: SleepInput) -> bool: # noqa: ARG002
        return True # sleep 不影響別的 tool

    def is_read_only(self, input: SleepInput) -> bool: # noqa: ARG002
        return True

    def max_result_size_chars(self) -> int | float:
        return 200
