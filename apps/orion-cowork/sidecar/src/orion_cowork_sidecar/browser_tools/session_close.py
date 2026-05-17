"""BrowserClose — 關掉當前 session 的 Chrome 視窗。"""
from __future__ import annotations

from collections.abc import AsyncIterator

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import TextEvent, ToolEvent, ToolInput
from orion_cowork_sidecar.browser_tools.session import close_browser_session


class BrowserCloseInput(ToolInput):
    pass


class BrowserCloseTool:
    name = "BrowserClose"
    description = (
        "Close the browser window for this conversation. Use when done with browsing "
        "tasks to free resources. A new Navigate will reopen it."
    )
    input_schema = BrowserCloseInput

    async def call(
        self, input: BrowserCloseInput, ctx: AgentContext,  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        closed = await close_browser_session(ctx.session_id)
        if closed:
            yield TextEvent(text="Browser closed.")
        else:
            yield TextEvent(text="Browser was not open.")

    def is_concurrency_safe(self, input: BrowserCloseInput) -> bool:  # noqa: ARG002
        return False
