"""ExitWorkdirTool — 從 cwd_stack pop 還原。

stack 空 → 回 ErrorEvent(沒地方退)。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput


class ExitWorkdirInput(ToolInput):
    """無參數。"""


class ExitWorkdirTool:
    name = "ExitWorkdir"
    description = (
        "Return to the previous working directory (pop the cwd stack). "
        "Pairs with EnterWorkdir."
    )
    input_schema = ExitWorkdirInput

    async def call(
        self,
        input: ExitWorkdirInput,  # noqa: ARG002
        ctx: AgentContext,
    ) -> AsyncIterator[ToolEvent]:
        if not ctx.cwd_stack:
            yield ErrorEvent(message="cwd stack is empty — nothing to exit")
            return

        prev = ctx.cwd_stack.pop()
        ctx.cwd = prev

        yield TextEvent(
            text=(
                f"exited to {prev} "
                f"(stack depth: {len(ctx.cwd_stack)})"
            ),
        )

    def is_concurrency_safe(self, input: ExitWorkdirInput) -> bool:  # noqa: ARG002
        return False

    def is_read_only(self, input: ExitWorkdirInput) -> bool:  # noqa: ARG002
        return False

    def max_result_size_chars(self) -> int | float:
        return 1_000
