"""BrowserClick — 點頁面元素(selector 或 visible text)。"""
from __future__ import annotations

from collections.abc import AsyncIterator

from pydantic import Field

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput
from orion_sdk.tools.browser.session import get_browser_session


class BrowserClickInput(ToolInput):
    selector: str | None = Field(
        None,
        description="CSS / XPath selector(優先);例 'button.submit'、'#login'。"
    )
    text: str | None = Field(
        None,
        description="Visible text to click(selector 沒給時 fallback)— get_by_text 對應。"
    )


class BrowserClickTool:
    name = "BrowserClick"
    description = (
        "Click an element on the current page. Provide either `selector` (CSS) "
        "or `text` (visible text). At least one is required."
    )
    input_schema = BrowserClickInput

    async def call(
        self, input: BrowserClickInput, ctx: AgentContext,
    ) -> AsyncIterator[ToolEvent]:
        if not input.selector and not input.text:
            yield ErrorEvent(message="Must provide either `selector` or `text`")
            return
        try:
            sess = await get_browser_session(ctx.session_id)
            if input.selector:
                await sess.page.click(input.selector, timeout=10_000)
                yield TextEvent(text=f"Clicked: {input.selector}")
            else:
                locator = sess.page.get_by_text(input.text or "", exact=False)
                await locator.first.click(timeout=10_000)
                yield TextEvent(text=f"Clicked text: {input.text!r}")
        except Exception as e:  # noqa: BLE001
            yield ErrorEvent(message=f"click failed: {e}")

    def is_concurrency_safe(self, input: BrowserClickInput) -> bool:  # noqa: ARG002
        return False
