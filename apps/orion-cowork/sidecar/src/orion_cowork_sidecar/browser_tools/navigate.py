"""BrowserNavigate / BrowserBack / BrowserForward — 頁面導覽。"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal

from pydantic import Field

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput
from orion_cowork_sidecar.browser_tools.session import get_browser_session


class BrowserNavigateInput(ToolInput):
    url: str = Field(..., description="HTTP/HTTPS URL to navigate to.")
    wait_for: Literal["load", "domcontentloaded", "networkidle"] = Field(
        "load",
        description=(
            "Wait condition before returning. "
            "'load' = window load event(default), "
            "'domcontentloaded' = DOM ready(faster), "
            "'networkidle' = 500ms no requests(slower, more reliable for SPA)."
        ),
    )


class BrowserNavigateTool:
    name = "BrowserNavigate"
    description = (
        "Open a URL in the user's Chrome browser (visible, system Chrome). "
        "Reuses the same browser window across calls in the same conversation."
    )
    input_schema = BrowserNavigateInput

    async def call(
        self, input: BrowserNavigateInput, ctx: AgentContext,
    ) -> AsyncIterator[ToolEvent]:
        url = input.url.strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            yield ErrorEvent(message=f"URL must start with http:// or https://: {url!r}")
            return
        try:
            sess = await get_browser_session(ctx.session_id)
            await sess.page.goto(url, wait_until=input.wait_for, timeout=30_000)
            title = await sess.page.title()
            final_url = sess.page.url
            yield TextEvent(text=f"Navigated to {final_url}\nTitle: {title}")
        except Exception as e:  # noqa: BLE001
            yield ErrorEvent(message=f"navigate failed: {e}")

    def is_concurrency_safe(self, input: BrowserNavigateInput) -> bool:  # noqa: ARG002
        return False

    def is_read_only(self, input: BrowserNavigateInput) -> bool:  # noqa: ARG002
        return False


class BrowserBackInput(ToolInput):
    pass


class BrowserBackTool:
    name = "BrowserBack"
    description = "Go back one entry in browser history."
    input_schema = BrowserBackInput

    async def call(
        self, input: BrowserBackInput, ctx: AgentContext,  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        try:
            sess = await get_browser_session(ctx.session_id)
            await sess.page.go_back(wait_until="load", timeout=15_000)
            yield TextEvent(text=f"Back. Now at: {sess.page.url}")
        except Exception as e:  # noqa: BLE001
            yield ErrorEvent(message=f"back failed: {e}")

    def is_concurrency_safe(self, input: BrowserBackInput) -> bool:  # noqa: ARG002
        return False


class BrowserForwardInput(ToolInput):
    pass


class BrowserForwardTool:
    name = "BrowserForward"
    description = "Go forward one entry in browser history."
    input_schema = BrowserForwardInput

    async def call(
        self, input: BrowserForwardInput, ctx: AgentContext,  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        try:
            sess = await get_browser_session(ctx.session_id)
            await sess.page.go_forward(wait_until="load", timeout=15_000)
            yield TextEvent(text=f"Forward. Now at: {sess.page.url}")
        except Exception as e:  # noqa: BLE001
            yield ErrorEvent(message=f"forward failed: {e}")

    def is_concurrency_safe(self, input: BrowserForwardInput) -> bool:  # noqa: ARG002
        return False
