"""BrowserReadPage — 拿目前頁面渲染後的文字 / accessibility tree。"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal

from pydantic import Field

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput
from orion_cowork_sidecar.browser_tools.session import get_browser_session

_MAX_CHARS = 50_000


class BrowserReadPageInput(ToolInput):
    format: Literal["text", "aria"] = Field(
        "text",
        description=(
            "'text' = rendered plain text(JS executed); "
            "'aria' = accessibility tree(name + role + value structure, useful for "
            "finding elements to Click/Type)."
        ),
    )


class BrowserReadPageTool:
    name = "BrowserReadPage"
    description = (
        "Read the current page content. Use 'text' to get rendered text after JS, "
        "'aria' to get the accessibility tree for locating interactive elements."
    )
    input_schema = BrowserReadPageInput

    async def call(
        self, input: BrowserReadPageInput, ctx: AgentContext,
    ) -> AsyncIterator[ToolEvent]:
        try:
            sess = await get_browser_session(ctx.session_id)
            if input.format == "aria":
                snapshot = await sess.page.accessibility.snapshot()
                # 簡單序列化 — JSON dump 不深(避免超巨大 tree)
                import json
                raw = json.dumps(snapshot, ensure_ascii=False, indent=2)
            else:
                raw = await sess.page.evaluate("() => document.body.innerText || ''")
            if len(raw) > _MAX_CHARS:
                raw = raw[:_MAX_CHARS] + f"\n…(truncated, total {len(raw)} chars)"
            yield TextEvent(text=raw)
        except Exception as e:  # noqa: BLE001
            yield ErrorEvent(message=f"read page failed: {e}")

    def is_concurrency_safe(self, input: BrowserReadPageInput) -> bool:  # noqa: ARG002
        return False

    def is_read_only(self, input: BrowserReadPageInput) -> bool:  # noqa: ARG002
        return True
