"""BrowserType — 在 input/textarea 填字,可選 submit。"""
from __future__ import annotations

from collections.abc import AsyncIterator

from pydantic import Field

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput
from orion_sdk.tools.browser.session import get_browser_session


class BrowserTypeInput(ToolInput):
    selector: str = Field(
        ...,
        description="CSS / XPath selector for the input element. Example: 'input[name=q]'."
    )
    text: str = Field(..., description="Text to type into the field.")
    submit: bool = Field(
        False,
        description="If true, press Enter after typing(submit form / trigger search)."
    )
    clear_first: bool = Field(
        True,
        description="Clear existing value before typing(default true)."
    )


class BrowserTypeTool:
    name = "BrowserType"
    description = (
        "Type text into an input / textarea element on the current page. "
        "Optionally press Enter to submit."
    )
    input_schema = BrowserTypeInput

    async def call(
        self, input: BrowserTypeInput, ctx: AgentContext,
    ) -> AsyncIterator[ToolEvent]:
        try:
            sess = await get_browser_session(ctx.session_id)
            if input.clear_first:
                await sess.page.fill(input.selector, "", timeout=10_000)
            await sess.page.fill(input.selector, input.text, timeout=10_000)
            if input.submit:
                await sess.page.press(input.selector, "Enter", timeout=10_000)
            yield TextEvent(
                text=f"Typed into {input.selector}: {input.text[:80]}"
                + ("(submitted)" if input.submit else "")
            )
        except Exception as e:  # noqa: BLE001
            yield ErrorEvent(message=f"type failed: {e}")

    def is_concurrency_safe(self, input: BrowserTypeInput) -> bool:  # noqa: ARG002
        return False
