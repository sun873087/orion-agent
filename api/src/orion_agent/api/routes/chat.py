"""WebSocket /chat/stream/{session_id} — 主互動端點。

對應 spec § 5 chat.py。

Lifecycle:
1. accept ws connection
2. 從 query string ?token=... 取 JWT 驗證
3. 從 SessionManager 取 Conversation(找不到 → 自動建)
4. 三個 concurrent task:
   - **writer**: outbound_queue → ws.send_json
   - **reader**: ws.receive_json → 派發 client event(UserMessage / PermissionDecision / Abort)
   - **runner**(spawn per UserMessage):跑 conv.send,把 LoopEvent 轉 ServerEvent push 進 queue

設計:
- 一次只跑一個 turn(turn_lock)— 第二個 user_message 在前一個結束前 reject
- Permission round-trip 透過 PendingPermissions(asyncio.Future + 60s timeout)
- WebSocketDisconnect 即時 cleanup,不 leak task
"""

from __future__ import annotations

import contextlib
from typing import Annotated, Any
from uuid import UUID

import anyio
import jwt
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel

from orion_agent.api.auth import verify_token
from orion_agent.api.deps import get_llm_provider, get_session_manager
from orion_agent.api.event_schema import (
    AbortEvent,
    AssistantTextEvent,
    AssistantThinkingEvent,
    ErrorEvent,
    HistoryReplayDoneEvent,
    PermissionDecisionEvent,
    ServerEvent,
    TerminalEvent,
    ToolResultEvent,
    ToolUseEvent,
    TurnCompleteEvent,
    UserMessageEvent,
    UserTextEvent,
    parse_client_event,
    serialize_server_event,
)
from orion_agent.api.session_manager import SessionManager
from orion_agent.api.ws_permissions import (
    PendingPermissions,
    make_can_use_tool_for_websocket,
)
from orion_agent.core.conversation import Conversation
from orion_agent.core.query_loop import (
    AssistantTextDelta,
    AssistantThinkingDelta,
    AssistantTurnComplete,
    LoopEvent,
    LoopTerminated,
)
from orion_agent.core.state import AgentContext
from orion_agent.core.tool_execution import (
    ToolProgressUpdate,
    ToolResultUpdate,
)
from orion_agent.llm.provider import LLMProvider
from orion_agent.llm.types import (
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)

router = APIRouter()


# 寫作 sentinel — None 進 queue → writer 結束
_QUEUE_SENTINEL = object()


async def _replay_history(websocket: WebSocket, conv: Conversation) -> None:
    """把 conversation 已有訊息翻成 ServerEvent 序列推給 client(用於 reconnect / 換 session)。"""
    tool_id_to_name: dict[str, str] = {}

    async def _send(ev: BaseModel) -> None:
        with contextlib.suppress(Exception):
            await websocket.send_json(serialize_server_event(ev))

    for msg in conv.state_messages:
        content = msg.content
        blocks = (
            [TextBlock(text=content)]
            if isinstance(content, str)
            else list(content)
        )
        for block in blocks:
            if isinstance(block, TextBlock):
                if msg.role == "user":
                    await _send(UserTextEvent(text=block.text))
                elif msg.role == "assistant":
                    await _send(AssistantTextEvent(text=block.text))
                # system role 不顯示
            elif isinstance(block, ThinkingBlock):
                await _send(AssistantThinkingEvent(text=block.text))
            elif isinstance(block, ToolUseBlock):
                tool_id_to_name[block.id] = block.name
                await _send(
                    ToolUseEvent(
                        tool_use_id=block.id,
                        tool_name=block.name,
                        input=block.input,
                    ),
                )
            elif isinstance(block, ToolResultBlock):
                if isinstance(block.content, str):
                    content_str = block.content
                else:
                    content_str = "\n".join(
                        b.text for b in block.content
                        if isinstance(b, TextBlock)
                    )
                await _send(
                    ToolResultEvent(
                        tool_use_id=block.tool_use_id,
                        tool_name=tool_id_to_name.get(block.tool_use_id, ""),
                        content=content_str,
                        is_error=block.is_error,
                    ),
                )
            # ImageBlock / TombstoneBlock skip(replay 不顯示)

    await _send(HistoryReplayDoneEvent())


def _loop_to_server_events(ev: LoopEvent) -> list[ServerEvent]:
    """LoopEvent(query_loop yield)→ ServerEvent(送給 ws client)。"""
    if isinstance(ev, AssistantTextDelta):
        return [AssistantTextEvent(text=ev.text)]
    if isinstance(ev, AssistantThinkingDelta):
        return [AssistantThinkingEvent(text=ev.text)]
    if isinstance(ev, AssistantTurnComplete):
        return [
            TurnCompleteEvent(
                stop_reason=ev.stop_reason,
                input_tokens=ev.input_tokens,
                output_tokens=ev.output_tokens,
            )
        ]
    if isinstance(ev, ToolProgressUpdate):
        # 工具開始 emit progress(內含 tool_use)— 我們只在第一次推 ToolUseEvent
        # 細節 progress(streaming text from tool)目前不轉,留 server 內部
        return []
    if isinstance(ev, ToolResultUpdate):
        # 從 message.content 取 ToolResultBlock 文字
        text = ""
        if isinstance(ev.message.content, list):
            for block in ev.message.content:
                if isinstance(block, ToolResultBlock):
                    text = (
                        block.content
                        if isinstance(block.content, str)
                        else str(block.content)
                    )
                    break
        return [
            ToolResultEvent(
                tool_use_id=ev.tool_use_id,
                tool_name=ev.tool_name,
                content=text,
                is_error=ev.is_error,
            )
        ]
    if isinstance(ev, LoopTerminated):
        return [
            TerminalEvent(
                reason=ev.transition.reason,
                total_turns=ev.total_turns,
            )
        ]
    return []


async def _emit_tool_use_for_assistant_turn(
    turn_complete: AssistantTurnComplete,
    outbound: anyio.abc.ObjectSendStream[Any] | None = None,  # noqa: ARG001
    queue: anyio.abc.ObjectSendStream[Any] | None = None,     # noqa: ARG001
) -> list[ServerEvent]:
    """從 AssistantTurnComplete.message 取 ToolUseBlock,產 ToolUseEvent。

    TurnComplete 後馬上送 ToolUse 訊息給 client(讓 UI 提早顯示「呼叫 X 工具中」)。
    """
    from orion_agent.llm.types import ToolUseBlock

    out: list[ServerEvent] = []
    if not isinstance(turn_complete.message.content, list):
        return out
    for block in turn_complete.message.content:
        if isinstance(block, ToolUseBlock):
            out.append(
                ToolUseEvent(
                    tool_use_id=block.id,
                    tool_name=block.name,
                    input=block.input,
                )
            )
    return out


@router.websocket("/chat/stream/{session_id}")
async def chat_stream(
    websocket: WebSocket,
    session_id: UUID,
    token: Annotated[str, Query(...)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
    provider: Annotated[LLMProvider, Depends(get_llm_provider)],
) -> None:
    """主 chat WebSocket。"""
    # ─── auth ───────────────────────────────────────────────────────────
    try:
        user_id = verify_token(token)
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError) as e:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason=f"invalid token: {e}",
        )
        return

    # ─── lookup / auto-create conversation ──────────────────────────────
    conv = await sm.get(user_id, session_id)
    if conv is None:
        from orion_agent.tools.builtin_set import build_default_tool_set
        conv = Conversation(
            provider=provider,
            user_id=user_id,
            session_id=session_id,
            tools=build_default_tool_set(),
        )
        await sm.create(
            user_id=user_id, session_id=session_id, conversation=conv,
        )

    await websocket.accept()

    # ─── 重播歷史 ───────────────────────────────────────────────────────
    # 把 conv.state_messages 翻回 ServerEvent 序列,讓剛連上的 client 看到過去對話
    await _replay_history(websocket, conv)

    # ─── 共享 state ─────────────────────────────────────────────────────
    outbound_send, outbound_recv = anyio.create_memory_object_stream[Any](
        max_buffer_size=128,
    )
    pending_perms = PendingPermissions()
    abort_event = anyio.Event()
    turn_lock = anyio.Lock()

    # 注入 ws-based permission callback
    conv.can_use_tool = make_can_use_tool_for_websocket(
        outbound_queue=outbound_send,  # type: ignore[arg-type]
        pending=pending_perms,
    )

    async def writer() -> None:
        async with outbound_recv:
            async for ev in outbound_recv:
                if ev is _QUEUE_SENTINEL:
                    return
                try:
                    await websocket.send_json(serialize_server_event(ev))
                except Exception:  # noqa: BLE001 — ws 死了就退
                    return

    async def runner(user_text: str) -> None:
        async with turn_lock:
            ctx = AgentContext(
                session_id=session_id,
                user_id=user_id,
                abort_event=abort_event,
            )
            try:
                async for loop_ev in conv.send(user_text, ctx=ctx):
                    for sev in _loop_to_server_events(loop_ev):
                        await outbound_send.send(sev)
                    # AssistantTurnComplete 後立刻附帶 ToolUseEvent(讓 UI 早顯示)
                    if isinstance(loop_ev, AssistantTurnComplete):
                        for tu_ev in await _emit_tool_use_for_assistant_turn(loop_ev):
                            await outbound_send.send(tu_ev)
            except Exception as e:  # noqa: BLE001
                await outbound_send.send(
                    ErrorEvent(message=f"{type(e).__name__}: {e}"),
                )

    async def reader(tg: anyio.abc.TaskGroup) -> None:
        try:
            while True:
                try:
                    raw = await websocket.receive_json()
                except WebSocketDisconnect:
                    return
                try:
                    cev = parse_client_event(raw)
                except Exception as e:  # noqa: BLE001
                    await outbound_send.send(
                        ErrorEvent(message=f"bad client event: {e}"),
                    )
                    continue

                if isinstance(cev, UserMessageEvent):
                    if turn_lock.statistics().tasks_waiting > 0 or turn_lock.locked():
                        await outbound_send.send(
                            ErrorEvent(message="a turn is already in progress"),
                        )
                        continue
                    tg.start_soon(runner, cev.content)
                elif isinstance(cev, PermissionDecisionEvent):
                    pending_perms.resolve(cev.request_id, cev.decision)
                elif isinstance(cev, AbortEvent):
                    abort_event.set()
        finally:
            # 通知 writer 退出
            await outbound_send.send(_QUEUE_SENTINEL)
            await outbound_send.aclose()

    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(writer)
            await reader(tg)
    except Exception as e:  # noqa: BLE001
        # 若 ws 還活著,嘗試送 error 通知
        with contextlib.suppress(Exception):
            await websocket.send_json(
                serialize_server_event(
                    ErrorEvent(message=f"server error: {type(e).__name__}: {e}"),
                ),
            )
    finally:
        with contextlib.suppress(Exception):
            await websocket.close()
