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
import json
import time
from typing import Annotated, Any
from uuid import UUID

import anyio
import jwt
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel

from orion_chat_api.auth import verify_token
from orion_chat_api.deps import get_llm_provider, get_session_manager
from orion_chat_api.event_schema import (
    AbortEvent,
    AskUserAnswerEvent,
    AskUserQuestionAskEvent,
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
from orion_chat_api.session_manager import SessionManager
from orion_chat_api.ws_permissions import (
    PendingPermissions,
    make_can_use_tool_for_websocket,
)
from orion_sdk.core.conversation import Conversation
from orion_sdk.core.query_loop import (
    AssistantTextDelta,
    AssistantThinkingDelta,
    AssistantTurnComplete,
    LoopEvent,
    LoopTerminated,
)
from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool_execution import (
    ToolProgressUpdate,
    ToolResultUpdate,
)
from orion_model.provider import LLMProvider
from orion_model.types import (
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from orion_sdk.storage.paths import session_paths
from orion_sdk.tools.interactive.ask_user import (
    AskUserQuestionTool,
    PendingQuestions,
    make_ws_asker,
)

router = APIRouter()


# 寫作 sentinel — None 進 queue → writer 結束
_QUEUE_SENTINEL = object()


_REPLAY_BATCH_SIZE = 100


async def _replay_history(websocket: WebSocket, conv: Conversation) -> None:
    """把 conversation 已有訊息翻成 ServerEvent 序列推給 client(用於 reconnect / 換 session)。

    Batched:每 100 events 包成 JSON array 送一個 frame,frontend 偵測 array
    就 spread 進 pending buffer。長 session(數百 blocks)不再一個一個 await
    ws.send_json,proxy 來回 + JSON encode 的 N×overhead 砍 ~100×。
    """
    tool_id_to_name: dict[str, str] = {}
    batch: list[dict[str, Any]] = []

    async def flush() -> None:
        if not batch:
            return
        with contextlib.suppress(Exception):
            await websocket.send_text(json.dumps(batch))
        batch.clear()

    def push(ev: BaseModel) -> None:
        batch.append(serialize_server_event(ev))

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
                    push(UserTextEvent(text=block.text))
                elif msg.role == "assistant":
                    push(AssistantTextEvent(text=block.text))
                # system role 不顯示
            elif isinstance(block, ThinkingBlock):
                push(AssistantThinkingEvent(text=block.text))
            elif isinstance(block, ToolUseBlock):
                tool_id_to_name[block.id] = block.name
                push(
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
                push(
                    ToolResultEvent(
                        tool_use_id=block.tool_use_id,
                        tool_name=tool_id_to_name.get(block.tool_use_id, ""),
                        content=content_str,
                        is_error=block.is_error,
                    ),
                )
            # ImageBlock / TombstoneBlock skip(replay 不顯示)

            if len(batch) >= _REPLAY_BATCH_SIZE:
                await flush()

    await flush()
    with contextlib.suppress(Exception):
        await websocket.send_json(
            serialize_server_event(HistoryReplayDoneEvent()),
        )


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
    from orion_model.types import ToolUseBlock

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
        from orion_sdk.core.conversation import pick_max_tokens_per_turn
        from orion_sdk.tools.builtin_set import build_default_tool_set
        conv = Conversation(
            provider=provider,
            user_id=user_id,
            session_id=session_id,
            tools=build_default_tool_set(),
            max_tokens_per_turn=pick_max_tokens_per_turn(
                provider.name, provider.model,
            ),
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
    pending_questions = PendingQuestions()
    abort_event = anyio.Event()
    turn_lock = anyio.Lock()

    # 注入 ws-based permission callback
    conv.can_use_tool = make_can_use_tool_for_websocket(
        outbound_queue=outbound_send,  # type: ignore[arg-type]
        pending=pending_perms,
    )

    # 把 ws asker 掛到 AskUserQuestionTool(per-connection late-bind)。
    # tool 本身在 build_default_tool_set 已註冊;這裡只設 callback,讓模型呼叫
    # 時能 round-trip 回前端。離線時用 try/finally 清掉,避免 closure 殘留。
    ask_tool: AskUserQuestionTool | None = next(
        (t for t in conv.tools if isinstance(t, AskUserQuestionTool)),
        None,
    )
    if ask_tool is not None:
        ask_tool.asker = make_ws_asker(
            outbound_queue=outbound_send,
            pending=pending_questions,
            event_factory=lambda rid, qs, t: AskUserQuestionAskEvent(
                request_id=rid, questions=qs, timeout_seconds=int(t),
            ),
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

    # 建 per-session workspace dir(模型用 Bash / Write 等寫檔的隔離 cwd)
    sp = session_paths(session_id)
    sp.ensure_dirs()

    async def runner(user_text: str) -> None:
        async with turn_lock:
            ctx = AgentContext(
                session_id=session_id,
                user_id=user_id,
                abort_event=abort_event,
                cwd=sp.workspace_dir,
            )

            # Coalesce text/thinking deltas — 避免每 token 一個 ws frame
            # (Anthropic 50–100 tokens/s × frame overhead 在 vite proxy 後
            # 容易塞)。30ms 視窗 opportunistic flush:延遲可忽略,frame 數
            # 砍 5–10×。非 delta event 來時強制先 flush 保持順序。
            text_buf: list[str] = []
            think_buf: list[str] = []
            last_flush = time.monotonic()
            FLUSH_INTERVAL = 0.03

            async def flush_text() -> None:
                nonlocal last_flush
                if text_buf:
                    await outbound_send.send(
                        AssistantTextEvent(text="".join(text_buf)),
                    )
                    text_buf.clear()
                if think_buf:
                    await outbound_send.send(
                        AssistantThinkingEvent(text="".join(think_buf)),
                    )
                    think_buf.clear()
                last_flush = time.monotonic()

            try:
                async for loop_ev in conv.send(user_text, ctx=ctx):
                    for sev in _loop_to_server_events(loop_ev):
                        if isinstance(sev, AssistantTextEvent):
                            text_buf.append(sev.text)
                            if time.monotonic() - last_flush >= FLUSH_INTERVAL:
                                await flush_text()
                        elif isinstance(sev, AssistantThinkingEvent):
                            think_buf.append(sev.text)
                            if time.monotonic() - last_flush >= FLUSH_INTERVAL:
                                await flush_text()
                        else:
                            await flush_text()
                            await outbound_send.send(sev)
                    # AssistantTurnComplete 後立刻附帶 ToolUseEvent(讓 UI 早顯示)
                    if isinstance(loop_ev, AssistantTurnComplete):
                        await flush_text()
                        for tu_ev in await _emit_tool_use_for_assistant_turn(loop_ev):
                            await outbound_send.send(tu_ev)
                await flush_text()
            except Exception as e:  # noqa: BLE001
                await flush_text()
                await outbound_send.send(
                    ErrorEvent(message=f"{type(e).__name__}: {e}"),
                )
            finally:
                # turn 結束(成功 / abort / 例外)都把 stats 落 DB,讓 sidebar 顯示
                # 真實 n_messages / n_turns 而不是 0。in-memory SessionManager 是 no-op。
                with contextlib.suppress(Exception):
                    await sm.sync_stats(user_id, session_id)

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
                elif isinstance(cev, AskUserAnswerEvent):
                    # 解 future → tool 拿到答案 → tool_result 回 model
                    pending_questions.resolve(cev.request_id, cev.answers)
                    # echo 一條 UserText 給 UI(display-only,不寫 conv state),
                    # 讓使用者親眼看到「自己回答了什麼」,也方便對照 model 是否真的
                    # 收到答案還是同題再問。空 answers 表示使用者放棄/取消。
                    if cev.answers:
                        echo = "\n".join(
                            f"Q: {q}\nA: {a}" for q, a in cev.answers.items()
                        )
                        await outbound_send.send(UserTextEvent(text=echo))
                    print(  # 後端 console 一行,debug 用
                        f"[ask_user_answer] rid={cev.request_id} "
                        f"answers={cev.answers}",
                        flush=True,
                    )
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
        # 清掉 ws-bound asker(closure 抓住本連線的 outbound_send,留著會 leak)
        if ask_tool is not None:
            ask_tool.asker = None
        with contextlib.suppress(Exception):
            await websocket.close()
