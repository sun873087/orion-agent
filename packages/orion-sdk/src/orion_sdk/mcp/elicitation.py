"""MCP elicitation(-32042 error)— stub。

對應 spec § 5 elicitation.py(Phase 5b)。

當 MCP server 在 call_tool 過程中需要反問 user(例:auth method 選擇、確認執行等),
會回 JSON-RPC error code -32042 + 結構化問題。Spec 說 Phase 5 階段不實作 — 罕用,
等實際碰到再做。

目前函式 raise NotImplementedError + 訊息指 Phase 5b。
"""

from __future__ import annotations

from typing import Any


def handle_elicitation_error(error: Any) -> Any:  # noqa: ARG001
    """Phase 5 不實作。"""
    raise NotImplementedError(
        "MCP elicitation (-32042) handling deferred to Phase 5b — "
        "no real-world server has tripped this yet"
    )
