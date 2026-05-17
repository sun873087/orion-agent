"""BrowserWaitFor — 等 selector 出現或 timeout。"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal

from pydantic import Field

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput
from orion_sdk.tools.browser.session import get_browser_session


class BrowserWaitForInput(ToolInput):
    selector: str = Field(..., description="CSS selector to wait for.")
    state: Literal["attached", "detached", "visible", "hidden"] = Field(
        "visible",
        description="State to wait for. 'visible' is most common."
    )
    timeout: int = Field(5000, ge=100, le=60000, description="Timeout in ms.")


class BrowserWaitForTool:
    name = "BrowserWaitFor"
    description = (
        "Wait for an element matching `selector` to reach `state`. "
        "Use after Click/Navigate when next page elements load asynchronously."
    )
    input_schema = BrowserWaitForInput

    async def call(
        self, input: BrowserWaitForInput, ctx: AgentContext,
    ) -> AsyncIterator[ToolEvent]:
        try:
            sess = await get_browser_session(ctx.session_id)
            await sess.page.wait_for_selector(
                input.selector, state=input.state, timeout=input.timeout,
            )
            yield TextEvent(text=f"OK: {input.selector} → {input.state}")
        except Exception as e:  # noqa: BLE001
            yield ErrorEvent(message=f"wait failed: {e}")

    def is_concurrency_safe(self, input: BrowserWaitForInput) -> bool:  # noqa: ARG002
        return False

    def is_read_only(self, input: BrowserWaitForInput) -> bool:  # noqa: ARG002
        return True
