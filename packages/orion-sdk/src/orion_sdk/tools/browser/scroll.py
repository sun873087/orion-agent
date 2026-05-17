"""BrowserScroll — 捲動頁面。"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal

from pydantic import Field

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput
from orion_sdk.tools.browser.session import get_browser_session


class BrowserScrollInput(ToolInput):
    direction: Literal["up", "down", "top", "bottom"] = Field(
        "down",
        description="'up' / 'down' = relative scroll by `amount`px; 'top' / 'bottom' = jump to ends."
    )
    amount: int = Field(500, ge=1, le=20000, description="Pixels to scroll(direction up/down only).")


class BrowserScrollTool:
    name = "BrowserScroll"
    description = "Scroll the current page up/down by N pixels, or jump to top/bottom."
    input_schema = BrowserScrollInput

    async def call(
        self, input: BrowserScrollInput, ctx: AgentContext,
    ) -> AsyncIterator[ToolEvent]:
        try:
            sess = await get_browser_session(ctx.session_id)
            if input.direction == "top":
                await sess.page.evaluate("window.scrollTo(0, 0)")
                yield TextEvent(text="Scrolled to top")
            elif input.direction == "bottom":
                await sess.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                yield TextEvent(text="Scrolled to bottom")
            else:
                delta = input.amount if input.direction == "down" else -input.amount
                await sess.page.evaluate(f"window.scrollBy(0, {delta})")
                yield TextEvent(text=f"Scrolled {input.direction} {input.amount}px")
        except Exception as e:  # noqa: BLE001
            yield ErrorEvent(message=f"scroll failed: {e}")

    def is_concurrency_safe(self, input: BrowserScrollInput) -> bool:  # noqa: ARG002
        return False
