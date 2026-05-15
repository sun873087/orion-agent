"""RPC method handlers — 連 orion-sdk Conversation。

Phase E PoC scope:
  - ping
  - conversation.create
  - conversation.send
  - conversation.abort

之後加 resume / list / memory / settings 等。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from dotenv import load_dotenv

from orion_model.provider import get_provider
from orion_sdk.core.conversation import Conversation
from orion_sdk.services.feature_flags import load_feature_flags
from orion_sdk.core.state import AgentContext
from orion_sdk.tools.builtin_set import build_default_tool_set

from orion_cowork_sidecar.streaming import to_rpc_frame

load_dotenv()


class Handlers:
    """In-memory store of active Conversations,keyed by session_id (str UUID)。

    Cowork single-user 本機 app — 不需要 per-user isolation。
    Process restart 等於丟 state(state 之後存 ~/.orion/sessions/...,Phase E+1)。
    """

    def __init__(self) -> None:
        self._conversations: dict[str, Conversation] = {}
        self._aborts: dict[str, AgentContext] = {}

    # ─── Dispatch table ─────────────────────────────────────────────────
    def methods(self) -> dict[str, Any]:
        return {
            "ping": self.ping,
            "conversation.create": self.conversation_create,
            "conversation.send": self.conversation_send,
            "conversation.abort": self.conversation_abort,
        }

    # ─── Methods ────────────────────────────────────────────────────────
    async def ping(self, _params: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        yield {"event": "pong", "final": True}

    async def conversation_create(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        provider_name = params.get("provider", "anthropic")
        model = params.get("model", "claude-sonnet-4-6")
        llm = get_provider(provider_name, model)
        tools = build_default_tool_set(asker=None)
        conv = Conversation(
            provider=llm,
            tools=tools,
            persistence_enabled=False,  # Phase E:in-memory only
            memory_enabled=False,
            auto_extract_memories=False,
        )
        sid = str(conv.session_id)
        self._conversations[sid] = conv
        yield {
            "event": "conversation_created",
            "data": {"session_id": sid, "provider": provider_name, "model": model},
            "final": True,
        }

    async def conversation_send(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        sid = params.get("session_id")
        prompt = params.get("prompt", "")
        if sid is None or sid not in self._conversations:
            yield {
                "event": "error",
                "data": {"code": "UNKNOWN_SESSION", "message": f"session {sid!r} not found"},
                "final": True,
            }
            return

        # 驗 UUID 格式
        try:
            UUID(sid)
        except (ValueError, TypeError):
            yield {
                "event": "error",
                "data": {"code": "BAD_SESSION_ID", "message": f"invalid UUID: {sid!r}"},
                "final": True,
            }
            return

        conv = self._conversations[sid]
        ctx = AgentContext(feature_flags=load_feature_flags(), user_id="cowork-local")
        self._aborts[sid] = ctx
        try:
            async for ev in conv.send(prompt, ctx=ctx):
                frame = to_rpc_frame(ev)
                if frame is not None:
                    yield frame
        finally:
            self._aborts.pop(sid, None)

    async def conversation_abort(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        sid = params.get("session_id")
        ctx = self._aborts.get(sid or "")
        if ctx is None:
            yield {
                "event": "no_active_turn",
                "data": {"session_id": sid},
                "final": True,
            }
            return
        ctx.abort_event.set()
        # Give the loop a chance to observe the abort
        await asyncio.sleep(0)
        yield {"event": "abort_requested", "data": {"session_id": sid}, "final": True}
