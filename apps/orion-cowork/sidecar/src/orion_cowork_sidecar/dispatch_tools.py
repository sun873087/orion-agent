"""Cowork DispatchPane tool — A pane 派工給 sibling pane(active push)。

跟 AskPane(read-only pull)互補:
- AskPane:讀 target pane 已做的事(transcript excerpt + status)
- DispatchPane:推訊息給 target pane,觸發新 turn

實際 dispatch 邏輯由 host(handlers.py)透過 callback 注入,tool 只是 LLM 入口。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Awaitable, Callable

from pydantic import Field

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput


DispatchCallback = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class DispatchPaneInput(ToolInput):
    pane_name: str = Field(
        ...,
        description=(
            "Target pane to dispatch the task to (e.g. '@frontend'). Must be a "
            "sibling pane in the same multi-pane collaboration window."
        ),
    )
    prompt: str = Field(
        ...,
        description=(
            "The task or instruction to deliver. Will appear in the target "
            "pane's conversation as a message tagged with your pane name. "
            "Keep it self-contained — the target pane has no access to your "
            "private context unless you spell it out here."
        ),
    )


class DispatchPaneTool:
    name = "DispatchPane"
    description = (
        "Send an actionable task to a sibling pane in the same multi-pane "
        "collaboration. The target pane receives your message as a new user "
        "turn and starts working on it autonomously.\n\n"
        "**Use DispatchPane** when the user says things like 'tell @frontend "
        "to render X' or 'ask @reviewer to look at Y' — you want the other "
        "pane to actively do something.\n\n"
        "**Use AskPane instead** when you only want to read what another pane "
        "has already done (transcript excerpt, status). DispatchPane is push; "
        "AskPane is pull.\n\n"
        "Behavior:\n"
        "- If the target is idle: fires immediately, you get status='fired'.\n"
        "- If the target is currently streaming: dispatch is queued and fires "
        "after they finish, you get status='queued' + queue_position.\n"
        "- If the target has opted out of inbound dispatches via Settings: "
        "you get status='rejected' with reason — fall back to AskPane or tell "
        "the user.\n\n"
        "Loop / abuse protection:\n"
        "- Cannot dispatch to yourself.\n"
        "- A pane already in the current dispatch chain cannot be dispatched "
        "to again (prevents A→B→A loops).\n"
        "- Max dispatch chain depth is 10 panes.\n\n"
        "Cost note: the target pane's turn counts against its own session "
        "ledger, not yours. User can see all costs in Settings."
    )
    input_schema = DispatchPaneInput

    def __init__(self, callback: DispatchCallback) -> None:
        # Callback by host (handlers.py) — knows current_session_id, current
        # pane_name, current_chain, engine, etc. Tool 本身不抓 sidecar state。
        self._callback = callback

    async def call(
        self,
        input: DispatchPaneInput,
        ctx: AgentContext, # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        pane_name = input.pane_name.strip()
        prompt = input.prompt.strip()
        if not pane_name:
            yield ErrorEvent(message="pane_name is empty")
            return
        if not prompt:
            yield ErrorEvent(message="prompt is empty")
            return
        try:
            result = await self._callback({
                "pane_name": pane_name,
                "prompt": prompt,
            })
        except Exception as e: # noqa: BLE001
            yield ErrorEvent(message=f"dispatch failed: {type(e).__name__}: {e}")
            return
        yield TextEvent(text=json.dumps(result, ensure_ascii=False, indent=2))

    def is_concurrency_safe(self, input: DispatchPaneInput) -> bool: # noqa: ARG002
        # Multiple dispatches in parallel is fine — they all go through SQL queue
        # with explicit chain validation.
        return True

    def is_read_only(self, input: DispatchPaneInput) -> bool: # noqa: ARG002
        # 觸發 target pane 跑新 turn,絕對不是 read-only
        return False

    def max_result_size_chars(self) -> int | float:
        return 4000
