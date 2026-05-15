"""把 SDK 的 LoopEvent / ToolUpdate 轉成 RPC frame dict。

跟 cli __main__.py 的 _render 跟 chat-api 的 event_schema 同源,只是
output 形式不一樣(這裡輸出 JSON-serializable dict)。
"""

from __future__ import annotations

from typing import Any

from orion_sdk.core.query_loop import (
    AssistantTextDelta,
    AssistantThinkingDelta,
    AssistantTurnComplete,
    LoopTerminated,
)
from orion_sdk.core.tool import ErrorEvent, ProgressEvent, TextEvent
from orion_sdk.core.tool_execution import ToolProgressUpdate, ToolResultUpdate


def to_rpc_frame(ev: Any) -> dict[str, Any] | None:
    """SDK event → RPC frame dict(無 id);None 代表此 event 不對外暴露。"""
    if isinstance(ev, AssistantTextDelta):
        return {"event": "text_delta", "data": {"text": ev.text}}

    if isinstance(ev, AssistantThinkingDelta):
        return {"event": "thinking_delta", "data": {"text": ev.text}}

    if isinstance(ev, AssistantTurnComplete):
        return {"event": "turn_complete", "data": {}}

    if isinstance(ev, ToolProgressUpdate):
        inner = ev.event
        if isinstance(inner, TextEvent):
            return None  # 由 ToolResultUpdate 統一顯示
        if isinstance(inner, ProgressEvent):
            return {
                "event": "tool_progress",
                "data": {
                    "tool_name": ev.tool_name,
                    "tool_use_id": ev.tool_use_id,
                    "progress": inner.data,
                },
            }
        if isinstance(inner, ErrorEvent):
            return {
                "event": "tool_error",
                "data": {
                    "tool_name": ev.tool_name,
                    "tool_use_id": ev.tool_use_id,
                    "message": inner.message,
                },
            }
        return None

    if isinstance(ev, ToolResultUpdate):
        first_block = ev.message.content[0] if isinstance(ev.message.content, list) else None
        text = ""
        if first_block is not None and hasattr(first_block, "content"):
            raw = first_block.content
            text = raw if isinstance(raw, str) else str(raw)
        return {
            "event": "tool_result",
            "data": {
                "tool_name": ev.tool_name,
                "tool_use_id": ev.tool_use_id,
                "is_error": ev.is_error,
                "text": text,
            },
        }

    if isinstance(ev, LoopTerminated):
        return {
            "event": "loop_terminated",
            "data": {
                "reason": ev.transition.reason,
                "total_turns": ev.total_turns,
            },
        }

    return None
