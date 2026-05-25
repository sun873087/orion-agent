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
    AutoCompactSuggestedEvent,
    BudgetExceededEvent,
    ErrorEvent,
    FollowUpsUpdatedEvent,
    HistoryReplayDoneEvent,
    PermissionDecisionEvent,
    ServerEvent,
    SessionTitleUpdatedEvent,
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
from orion_sdk.permissions.decisions import PermissionDecision, PermissionResult
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


async def _allow_all(
    _tool: Any, _tool_input: dict[str, Any], _ctx: Any,
) -> PermissionResult:
    """act 模式的 can_use_tool — 全放行。

    注意:SDK tool_execution 無條件 `await can_use_tool(...)`,所以 act 模式不能用
    None(會 TypeError),必須給一個真的回 ALLOW 的 callable。
    """
    return PermissionResult(decision=PermissionDecision.ALLOW)


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


def _msg_text(message: Any) -> str:
    """取一則 message 的純文字(content 可能是 str 或 block list)。"""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content if isinstance(content, list) else []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return " ".join(parts)


def _first_exchange_text(messages: list[Any]) -> tuple[str, str]:
    """取首個 user / assistant 文字(給標題 side-query 當輸入)。"""
    user_text = next(
        (_msg_text(m) for m in messages if getattr(m, "role", None) == "user"), "",
    )
    assistant_text = next(
        (_msg_text(m) for m in messages if getattr(m, "role", None) == "assistant"),
        "",
    )
    return user_text, assistant_text


async def _maybe_generate_title(
    conv: Conversation,
    sm: SessionManager,
    session_id: UUID,
    outbound: anyio.abc.ObjectSendStream[Any],
) -> None:
    """首輪後若尚無標題,跑 mini-model side-query 生標題、寫 DB、推 WS event。

    全程吞例外 — 標題生成失敗絕不影響對話。需 DB(in-memory manager 無 engine → 跳過)。
    """
    engine = getattr(sm, "engine", None)
    if engine is None:
        return
    try:
        from orion_chat_api.conversation_meta import fetch_meta_map, upsert_meta
        from orion_chat_api.title_gen import (
            generate_session_title,
            mini_provider_for,
        )

        existing, _ = (await fetch_meta_map(engine, [str(session_id)])).get(
            str(session_id), (None, False),
        )
        if existing:  # 已有標題,不重生
            return
        user_text, assistant_text = _first_exchange_text(conv.state_messages)
        if not user_text:
            return
        provider = conv.compact_summary_provider or mini_provider_for(conv.provider)
        title = await generate_session_title(
            provider, user_text, assistant_text,
            session_id=str(session_id), user_id=conv.user_id,
        )
        if not title:
            return
        await upsert_meta(engine, str(session_id), title=title)
        await outbound.send(
            SessionTitleUpdatedEvent(session_id=str(session_id), title=title),
        )
    except Exception:  # noqa: BLE001
        pass


async def _budget_blocked(sm: SessionManager, session_id: UUID) -> bool:
    """turn 開始前:該 session 是否已超預算(超了就不該再跑)。"""
    engine = getattr(sm, "engine", None)
    if engine is None:
        return False
    try:
        from orion_chat_api.conversation_meta import fetch_budget

        _, exceeded = await fetch_budget(engine, str(session_id))
        return exceeded
    except Exception:  # noqa: BLE001
        return False


async def _check_budget_and_notify(
    conv: Conversation,
    sm: SessionManager,
    session_id: UUID,
    outbound: anyio.abc.ObjectSendStream[Any],
) -> None:
    """turn 結束後:累積成本達 cap → set exceeded + push BudgetExceededEvent。"""
    engine = getattr(sm, "engine", None)
    if engine is None:
        return
    try:
        from orion_chat_api.conversation_meta import (
            budget_is_exceeded,
            fetch_budget,
            upsert_meta,
        )
        from orion_sdk.telemetry.cost_tracker import get_session_summary

        cap, already = await fetch_budget(engine, str(session_id))
        if cap is None or already:
            return
        summary = get_session_summary(str(session_id))
        total = float(summary["total_cost_usd"]) if summary else 0.0
        if budget_is_exceeded(total, cap):
            await upsert_meta(engine, str(session_id), budget_exceeded=True)
            await outbound.send(
                BudgetExceededEvent(
                    session_id=str(session_id), total_cost_usd=total, cap=cap,
                ),
            )
    except Exception:  # noqa: BLE001
        pass


async def _maybe_followups(
    conv: Conversation,
    session_id: UUID,
    outbound: anyio.abc.ObjectSendStream[Any],
) -> None:
    """turn 結束後產 follow-up 建議(mini model)→ push WS。失敗吞掉。"""
    try:
        from orion_chat_api.title_gen import generate_followups, mini_provider_for

        user_text, assistant_text = _first_exchange_text(
            list(reversed(conv.state_messages)),
        )
        if not assistant_text:
            return
        provider = conv.compact_summary_provider or mini_provider_for(conv.provider)
        suggestions = await generate_followups(
            provider, user_text, assistant_text,
            session_id=str(session_id), user_id=conv.user_id,
        )
        if suggestions:
            await outbound.send(
                FollowUpsUpdatedEvent(
                    session_id=str(session_id), suggestions=suggestions,
                ),
            )
    except Exception:  # noqa: BLE001
        pass


async def _maybe_auto_compact(
    conv: Conversation,
    session_id: UUID,
    outbound: anyio.abc.ObjectSendStream[Any],
) -> None:
    """context 逼近 model 上限(>=80%)→ push AutoCompactSuggestedEvent。"""
    try:
        max_ctx = getattr(conv.provider.capabilities, "max_context_tokens", 0) or 0
        if max_ctx <= 0:
            return
        approx = sum(len(_msg_text(m)) for m in conv.state_messages) // 4
        if approx >= max_ctx * 0.8:
            await outbound.send(
                AutoCompactSuggestedEvent(session_id=str(session_id)),
            )
    except Exception:  # noqa: BLE001
        pass


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
        from orion_chat_api.user_context import build_user_system_prefix
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
            # soul.md → system prompt 前綴(prepend,不覆蓋靜態段)
            system_prompt=build_user_system_prefix(user_id),
            # Chat-api server,無 user-side cwd
            include_workspace_context=False,
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

    # ws-based permission callback(ask 模式用);act 模式則設 None(全放行)。
    # 每個 turn 開始時依 permission_mode 切換(見 runner)。
    ws_can_use_tool = make_can_use_tool_for_websocket(
        outbound_queue=outbound_send,  # type: ignore[arg-type]
        pending=pending_perms,
    )
    conv.can_use_tool = ws_can_use_tool

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
            if await _budget_blocked(sm, session_id):
                await outbound_send.send(
                    ErrorEvent(
                        message="Budget cap reached for this conversation. "
                        "Raise the cap in settings to continue.",
                    ),
                )
                return
            # 依 permission_mode 切換:act → 全放行(can_use_tool=None);ask → ws round-trip
            # plan mode active/awaiting → 用 SDK plan_mode_aware 包(唯讀/全擋優先)。
            plan_status = "inactive"
            plan_content = ""
            cwd = sp.workspace_dir
            engine = getattr(sm, "engine", None)
            if engine is not None:
                from orion_chat_api.conversation_meta import (
                    fetch_permission_mode,
                    fetch_plan,
                    fetch_session_context,
                )
                from orion_chat_api.user_context import (
                    build_session_system_prefix,
                    project_workspace_dir,
                )

                mode = await fetch_permission_mode(engine, str(session_id))
                plan_status, plan_content = await fetch_plan(engine, str(session_id))
                # 每輪重算 system prefix(soul + active role + project 指令)→ 改設定下一輪生效
                conv.system_prompt = await build_session_system_prefix(
                    engine, user_id, str(session_id),
                )
                # custom instructions(只有 user-level,對齊 Cowork user_instructions)
                # → 交給 SDK assembler 放正確位置(不塞 prefix)。改了下一輪生效。
                from orion_sdk.prompt.instructions import get_custom_instructions
                from orion_sdk.storage.db.engine import db_session

                async with db_session(engine) as _db:
                    _inst = await get_custom_instructions(
                        user_id=user_id, session_id=None, db=_db,
                    )
                conv.custom_instructions_user = _inst.user_level
                # 屬某 project → 用 project 共享 workspace(sandbox 在 user 命名空間)
                proj_id, _ = await fetch_session_context(engine, str(session_id))
                if proj_id:
                    cwd = project_workspace_dir(user_id, proj_id)
                    cwd.mkdir(parents=True, exist_ok=True)
                # act → 全放行 callable(不可用 None — SDK 會無條件呼叫);ask → ws round-trip
                base = _allow_all if mode == "act" else ws_can_use_tool
                if plan_status != "inactive":
                    from orion_sdk.plan_mode import plan_mode_aware

                    conv.can_use_tool = plan_mode_aware(base)
                else:
                    conv.can_use_tool = base
            ctx = AgentContext(
                session_id=session_id,
                user_id=user_id,
                abort_event=abort_event,
                cwd=cwd,
            )
            if plan_status != "inactive":
                from orion_sdk.plan_mode.state import PlanModeState, PlanModeStatus

                ctx.plan_mode_state = PlanModeState(
                    status=PlanModeStatus(plan_status),
                    plan_content=plan_content,
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
                # 首輪後自動生成標題(內部 guard:已有標題 / 無 DB 則跳過)
                await _maybe_generate_title(conv, sm, session_id, outbound_send)
                # 成本治理 + context 將滿提示(內部 guard,失敗不影響對話)
                await _check_budget_and_notify(conv, sm, session_id, outbound_send)
                await _maybe_auto_compact(conv, session_id, outbound_send)
                await _maybe_followups(conv, session_id, outbound_send)
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

    # ─── 連 per-user remote MCP server(工具在本連線期間可用)──────────────
    # 生命週期綁 ws 連線(連線時連、斷線時關)→ 多租戶資源有界、多 worker 安全。
    # 連不上不該擋對話:best-effort,失敗就當沒 MCP。
    mcp_manager: Any = None
    original_tools = list(conv.tools)
    from orion_chat_api.mcp_loader import load_user_http_mcp_configs

    mcp_configs = load_user_http_mcp_configs(user_id)
    if mcp_configs:
        from orion_sdk.mcp.manager import McpManager

        mgr = McpManager(configs=mcp_configs)
        try:
            # 連線上限 8s — 黑洞 / 無回應的 server 不該卡住 ws 連線
            with anyio.fail_after(8):
                await mgr.__aenter__()
            mcp_manager = mgr
            conv.tools = [*original_tools, *mgr.tools]
        except Exception:  # noqa: BLE001 — MCP 連不上不影響對話
            with contextlib.suppress(Exception):
                await mgr.__aexit__(None, None, None)
            conv.tools = original_tools

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
        # 收掉 MCP 連線 + 還原 tool set(wrapped tool 的 client 已關,不能留在 cached conv)
        if mcp_manager is not None:
            with contextlib.suppress(Exception):
                await mcp_manager.__aexit__(None, None, None)
            conv.tools = original_tools
        # 清掉 ws-bound asker(closure 抓住本連線的 outbound_send,留著會 leak)
        if ask_tool is not None:
            ask_tool.asker = None
        with contextlib.suppress(Exception):
            await websocket.close()
