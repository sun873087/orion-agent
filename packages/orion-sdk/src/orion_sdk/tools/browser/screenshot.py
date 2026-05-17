"""BrowserScreenshot — 截圖回 ImageEvent,LLM 下輪 vision input。"""
from __future__ import annotations

import base64
from collections.abc import AsyncIterator

from pydantic import Field

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, ImageEvent, TextEvent, ToolEvent, ToolInput
from orion_sdk.tools.browser.session import get_browser_session


class BrowserScreenshotInput(ToolInput):
    full_page: bool = Field(
        False,
        description="If true, capture entire scrollable page; false = just viewport."
    )


class BrowserScreenshotTool:
    name = "BrowserScreenshot"
    description = (
        "Take a screenshot of the current page. The image is attached to the tool "
        "result so the LLM can see it in the next turn (vision-aware)."
    )
    input_schema = BrowserScreenshotInput

    async def call(
        self, input: BrowserScreenshotInput, ctx: AgentContext,
    ) -> AsyncIterator[ToolEvent]:
        try:
            sess = await get_browser_session(ctx.session_id)
            png_bytes = await sess.page.screenshot(full_page=input.full_page)
            b64 = base64.b64encode(png_bytes).decode("ascii")
            url = sess.page.url
            title = await sess.page.title()
            yield TextEvent(
                text=f"Screenshot taken ({len(png_bytes)} bytes) at: {url}\nTitle: {title}"
            )
            yield ImageEvent(media_type="image/png", data=b64)
        except Exception as e:  # noqa: BLE001
            yield ErrorEvent(message=f"screenshot failed: {e}")

    def is_concurrency_safe(self, input: BrowserScreenshotInput) -> bool:  # noqa: ARG002
        return False

    def is_read_only(self, input: BrowserScreenshotInput) -> bool:  # noqa: ARG002
        return True
