"""MCP elicitation(-32042 error)— stub。

對應 spec § 5 elicitation.py。

當 MCP server 在 call_tool 過程中需要反問 user(例:auth method 選擇、確認執行等),
會回 JSON-RPC error code -32042 + 結構化問題。Spec 說 階段不實作 — 罕用,
等實際碰到再做。

目前函式 raise NotImplementedError + 訊息指。
"""

from __future__ import annotations

from typing import Any


def handle_elicitation_error(error: Any) -> Any: # noqa: ARG001
    """不實作。"""
    raise NotImplementedError(
        "MCP elicitation (-32042) handling deferred to "
        "no real-world server has tripped this yet"
    )
