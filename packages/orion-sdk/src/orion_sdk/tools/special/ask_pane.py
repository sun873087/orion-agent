"""AskPaneTool — multi-pane collaboration 內 cross-pane query 工具。

協作 window 內 N 個 pane,各自獨立 session / model / persona。LLM 在 pane A
想知道「pane B 做了什麼」,呼 AskPane(pane_name="..."),host 從 DB 撈對方
session 最近 transcript + 跑得到哪一步 + partial output 回傳。

設計選擇:
- **非阻塞**:不會等對方 LLM 跑完;對方 busy 就回 status="running" + partial。
  A 的 LLM 自己決定:用 partial 繼續、跟 user 確認、或請 user 自己手動再問。
- **DB-only**:不去叫對方 sidecar 跑 turn,純 DB JOIN 讀 messages。對方多慢都不影響。
- **Host-injected callback**:SDK 不直接接 DB,給 sidecar / 其他 host 注入。

詳細設計見 `docs/roadmap/multi-pane-collaboration.md`。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Awaitable, Callable

from pydantic import Field

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput

AskPaneCallback = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
"""Host callback。Input: {requesting_session_id, pane_name, question?, n_recent_messages?}.
Output: {status, current_action?, transcript_excerpt, partial_output?, error?}.

status ∈ {"idle", "running", "done", "error", "not_found"}.
"not_found" 表示 collab 內沒 pane_name 對應的 pane(或 session 沒綁進 collab)。
"""


class AskPaneInput(ToolInput):
    pane_name: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description=(
            "Name of the other pane in the same collaboration (e.g. '@reviewer' "
            "or 'backend-coder'). Case-sensitive."
        ),
    )
    question: str | None = Field(
        default=None,
        max_length=2000,
        description=(
            "Optional: a question/topic you want pane to answer. Currently "
            "informational (logged for user observability); the host returns "
            "the recent transcript + status regardless. Future: may forward "
            "to that pane as a synthetic user message."
        ),
    )
    n_recent_messages: int = Field(
        default=8,
        ge=1,
        le=50,
        description=(
            "How many recent messages from the other pane to include in the "
            "transcript_excerpt. Default 8."
        ),
    )


class AskPaneTool:
    name = "AskPane"
    description = (
        "Ask another pane (agent) in the same collaboration what it has done "
        "or is currently doing. Returns its recent transcript + status (idle / "
        "running / done) + any partial output. Non-blocking — if the other "
        "pane is mid-stream, you get whatever it has so far plus a 'running' "
        "flag; decide yourself whether to use the partial, wait, or ask the "
        "user. Only works when this session is part of a multi-pane "
        "collaboration window."
    )
    input_schema = AskPaneInput

    def __init__(self, callback: AskPaneCallback | None = None) -> None:
        self._callback = callback

    async def call(
        self,
        input: AskPaneInput,
        ctx: AgentContext,
    ) -> AsyncIterator[ToolEvent]:
        if self._callback is None:
            yield ErrorEvent(
                message=(
                    "AskPane not wired — this session is not part of a "
                    "multi-pane collaboration, or host did not inject the "
                    "callback."
                )
            )
            return
        # ctx.session_id 是 UUID — host callback 期望 str
        requesting_sid_raw = getattr(ctx, "session_id", None)
        requesting_sid = str(requesting_sid_raw) if requesting_sid_raw else ""
        if not requesting_sid:
            yield ErrorEvent(
                message="AskPane requires AgentContext.session_id (host must set it)."
            )
            return
        params = {
            "requesting_session_id": requesting_sid,
            "pane_name": input.pane_name,
            "question": input.question,
            "n_recent_messages": input.n_recent_messages,
        }
        try:
            result = await self._callback(params)
        except ValueError as e:
            yield ErrorEvent(message=str(e))
            return
        except Exception as e:  # noqa: BLE001
            yield ErrorEvent(
                message=f"AskPane failed: {type(e).__name__}: {e}"
            )
            return
        if not isinstance(result, dict):
            yield ErrorEvent(message="AskPane callback returned malformed result")
            return
        if result.get("status") == "not_found":
            yield TextEvent(
                text=json.dumps({
                    "status": "not_found",
                    "pane_name": input.pane_name,
                    "hint": (
                        "No pane with this name in current collaboration. "
                        "Use the exact pane_name shown to you in the system "
                        "prompt's collaboration roster."
                    ),
                }, indent=2, ensure_ascii=False)
            )
            return
        # Echo the result back to LLM as structured JSON
        formatted = {
            "pane_name": result.get("pane_name") or input.pane_name,
            "pane_role": result.get("pane_role"),
            "status": result.get("status", "unknown"),
            "current_action": result.get("current_action"),
            "transcript_excerpt": result.get("transcript_excerpt") or [],
            "partial_output": result.get("partial_output"),
        }
        yield TextEvent(
            text=json.dumps(formatted, indent=2, ensure_ascii=False)
        )

    def is_concurrency_safe(self, input: AskPaneInput) -> bool:  # noqa: ARG002
        # 純讀,可並發
        return True

    def is_read_only(self, input: AskPaneInput) -> bool:  # noqa: ARG002
        return True

    def max_result_size_chars(self) -> int | float:
        return 50_000
