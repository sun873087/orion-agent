"""單一工具執行流程。對應 TS `src/services/tools/toolExecution.ts:run_tool_use`。

流程:
  1. find tool by name(找不到 → synthetic error result)
  2. validate input(parse 失敗 → synthetic error result)
  3. PreToolUse hook(回 False → 視同 deny)
  4. CanUseToolFn 詢問(deny → synthetic error result)
  5. tool.call(input, ctx)— async iterate,累積 events 成 result text
  6. PostToolUse hook(read-only)
  7. yield ToolResultUpdate(含 NormalizedMessage with ToolResultBlock)
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, ProgressEvent, TextEvent, Tool, ToolEvent
from orion_sdk.hooks.events import (
    FileChangedEvent,
    PostToolUseEvent,
    PostToolUseFailureEvent,
    PreToolUseEvent,
)
from orion_sdk.hooks.registry import HookRegistry
from orion_model.types import NormalizedMessage, ToolResultBlock
from orion_sdk.permissions.decisions import (
    CanUseToolFn,
    PermissionDecision,
)
from orion_sdk.storage.tool_result import maybe_persist_large_tool_result


@dataclass
class ToolUseStartUpdate:
    """工具開始執行時 emit 一次 — 帶 raw_input,給 UI 顯示「我在跑什麼」。

    對應 query_loop emit 順序:ToolUseStartUpdate → 0..N ToolProgressUpdate →
    ToolResultUpdate(每個 tool_use_id 一組)。
    """

    tool_use_id: str
    tool_name: str
    input: dict[str, Any]


@dataclass
class ToolProgressUpdate:
    """工具執行中的中間事件(TextEvent / ProgressEvent / ErrorEvent)。
    main loop 可印給 user 看,**不**累積到 state_messages。
    """

    tool_use_id: str
    tool_name: str
    event: ToolEvent


@dataclass
class ToolResultUpdate:
    """工具執行完成 — final 結果。message 會被 query_loop append 到 state_messages
    並回填給模型。
    """

    tool_use_id: str
    tool_name: str
    message: NormalizedMessage
    """role='user' 的 NormalizedMessage,content 含一個 ToolResultBlock。"""
    is_error: bool = False
    extra_notes: list[str] = field(default_factory=list)
    """例如 deny 原因、parse error 詳情等。"""


ToolUpdate = ToolUseStartUpdate | ToolProgressUpdate | ToolResultUpdate


def _make_result_message(
    tool_use_id: str,
    text: str,
    *,
    is_error: bool = False,
) -> NormalizedMessage:
    """打包 ToolResultBlock 成 user role 的 NormalizedMessage。"""
    return NormalizedMessage(
        role="user",
        content=[
            ToolResultBlock(
                tool_use_id=tool_use_id,
                content=text,
                is_error=is_error,
            )
        ],
    )


async def run_one_tool(
    tool_use_id: str,
    tool_name: str,
    raw_input: dict[str, Any],
    *,
    tools_by_name: dict[str, Tool[Any]],
    can_use_tool: CanUseToolFn,
    hooks: HookRegistry,
    ctx: AgentContext,
) -> AsyncIterator[ToolUpdate]:
    """單一 tool 執行流程,yield ToolProgressUpdate*,最後 yield 一個 ToolResultUpdate。

    Phase 9:wrap 一個 OTel span(`orion_agent.tool`),自動記 duration / errors。
    """
    # Phase 9:OTel span 包整個 generator
    import time

    from orion_sdk.telemetry.otel import (
        tool_duration as _tool_duration_metric,
    )
    from orion_sdk.telemetry.otel import (
        tool_errors as _tool_errors_metric,
    )
    from orion_sdk.telemetry.otel import (
        tracer as _tracer,
    )

    _span = _tracer.start_span(
        "orion_agent.tool",
        attributes={
            "tool.name": tool_name,
            "tool.use_id": tool_use_id,
            "session_id": str(ctx.session_id),
        },
    )
    _start_t = time.monotonic()
    _had_error = False
    try:
        # UI 顯示「在跑什麼」用的 start event(含 raw_input)。
        yield ToolUseStartUpdate(
            tool_use_id=tool_use_id, tool_name=tool_name, input=dict(raw_input),
        )
        async for upd in _run_one_tool_inner(
            tool_use_id, tool_name, raw_input,
            tools_by_name=tools_by_name,
            can_use_tool=can_use_tool,
            hooks=hooks,
            ctx=ctx,
        ):
            if isinstance(upd, ToolResultUpdate) and upd.is_error:
                _had_error = True
            yield upd
    finally:
        if _had_error:
            _tool_errors_metric().add(
                1, {"tool.name": tool_name, "session_id": str(ctx.session_id)},
            )
        _tool_duration_metric().record(
            (time.monotonic() - _start_t) * 1000,
            {"tool.name": tool_name, "session_id": str(ctx.session_id)},
        )
        _span.end()


async def _run_one_tool_inner(
    tool_use_id: str,
    tool_name: str,
    raw_input: dict[str, Any],
    *,
    tools_by_name: dict[str, Tool[Any]],
    can_use_tool: CanUseToolFn,
    hooks: HookRegistry,
    ctx: AgentContext,
) -> AsyncIterator[ToolUpdate]:
    """原 run_one_tool 內容(Phase 9 把它分出來;wrapper 加 OTel)。"""

    # ─── 1. find tool ───────────────────────────────────────────────────────
    tool = tools_by_name.get(tool_name)
    if tool is None:
        msg = _make_result_message(
            tool_use_id,
            f"Tool {tool_name!r} not found. Available: {sorted(tools_by_name)}",
            is_error=True,
        )
        yield ToolResultUpdate(
            tool_use_id=tool_use_id, tool_name=tool_name, message=msg, is_error=True,
        )
        return

    # ─── 2. validate input ──────────────────────────────────────────────────
    try:
        parsed_input = tool.input_schema.model_validate(raw_input)
    except ValidationError as e:
        msg = _make_result_message(
            tool_use_id,
            f"Invalid input for tool {tool_name!r}: {e}",
            is_error=True,
        )
        yield ToolResultUpdate(
            tool_use_id=tool_use_id, tool_name=tool_name, message=msg, is_error=True,
        )
        return

    # ─── 3. PreToolUse hook ─────────────────────────────────────────────────
    pre_event = PreToolUseEvent(
        tool=tool,
        tool_input=raw_input,
        ctx=ctx,
        session_id=str(ctx.session_id),
        user_id=ctx.user_id,
        tool_name=tool_name,
        tool_use_id=tool_use_id,
    )
    pre_result = await hooks.fire_pre_tool_use(pre_event)
    if pre_result.abort:
        reason = pre_result.abort_reason or "blocked by pre_tool_use hook"
        msg = _make_result_message(
            tool_use_id,
            f"Tool {tool_name!r} blocked by pre_tool_use hook: {reason}",
            is_error=True,
        )
        yield ToolResultUpdate(
            tool_use_id=tool_use_id, tool_name=tool_name, message=msg, is_error=True,
        )
        return
    # Phase 8:hook 可改 input(覆蓋 caller 給的)
    if pre_result.modified_input is not None:
        raw_input = pre_result.modified_input
        try:
            parsed_input = tool.input_schema.model_validate(raw_input)
        except ValidationError as e:
            msg = _make_result_message(
                tool_use_id,
                f"Hook modified_input failed schema for {tool_name!r}: {e}",
                is_error=True,
            )
            yield ToolResultUpdate(
                tool_use_id=tool_use_id, tool_name=tool_name, message=msg, is_error=True,
            )
            return

    # ─── 4. CanUseToolFn permission ─────────────────────────────────────────
    # 把 tool_use_id 暫時掛到 contextvar,讓 can_use_tool 內 await UI approval
    # 時可以拿來 reply 對應(Protocol 沒這 arg,改 signature 影響太大)。
    from orion_sdk.permissions.decisions import current_tool_use_id as _cur_tuid
    _tuid_tok = _cur_tuid.set(tool_use_id)
    try:
        perm = await can_use_tool(tool, raw_input, ctx)
    finally:
        _cur_tuid.reset(_tuid_tok)
    if perm.decision != PermissionDecision.ALLOW:
        reason = perm.reason or f"permission decision: {perm.decision.value}"
        msg = _make_result_message(
            tool_use_id,
            f"Tool {tool_name!r} not permitted — {reason}",
            is_error=True,
        )
        yield ToolResultUpdate(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            message=msg,
            is_error=True,
            extra_notes=[reason],
        )
        return

    # ─── 5. call tool, accumulate events ────────────────────────────────────
    text_chunks: list[str] = []
    error_msgs: list[str] = []
    try:
        async for event in tool.call(parsed_input, ctx):
            yield ToolProgressUpdate(
                tool_use_id=tool_use_id, tool_name=tool_name, event=event,
            )
            if isinstance(event, TextEvent):
                text_chunks.append(event.text)
            elif isinstance(event, ErrorEvent):
                error_msgs.append(event.message)
            elif isinstance(event, ProgressEvent):
                pass  # progress 不進結果
    except Exception as e:  # noqa: BLE001 — 工具任何例外都不該炸 loop
        error_msgs.append(f"Tool execution raised {type(e).__name__}: {e}")

    is_error = bool(error_msgs)
    if is_error:
        result_text = "\n".join(error_msgs)
        if text_chunks:
            result_text += "\n\n[partial output before error]:\n" + "\n".join(text_chunks)
    else:
        result_text = "\n".join(text_chunks) if text_chunks else "(tool produced no output)"

    # ─── 6. PostToolUse / PostToolUseFailure hook ────────────────────────
    if is_error:
        await hooks.fire(
            PostToolUseFailureEvent(
                tool=tool,
                tool_input=raw_input,
                error_message=result_text,
                ctx=ctx,
                session_id=str(ctx.session_id),
                user_id=ctx.user_id,
                tool_name=tool_name,
                tool_use_id=tool_use_id,
            ),
        )
    else:
        post_event = PostToolUseEvent(
            tool=tool,
            tool_input=raw_input,
            result_text=result_text,
            is_error=is_error,
            ctx=ctx,
            session_id=str(ctx.session_id),
            user_id=ctx.user_id,
            tool_name=tool_name,
            tool_use_id=tool_use_id,
        )
        await hooks.post_tool_use(post_event)

    # FileChanged event(Write / Edit 工具成功時)
    if not is_error and tool_name in ("Write", "Edit"):
        path = raw_input.get("path") if isinstance(raw_input, dict) else None
        if isinstance(path, str) and path:
            await hooks.fire(
                FileChangedEvent(
                    file_path=path,
                    change_type="modified" if tool_name == "Edit" else "created",
                    ctx=ctx,
                    session_id=str(ctx.session_id),
                    user_id=ctx.user_id,
                ),
            )

    # ─── 7. Phase 2 第 2 層持久化:大結果寫檔 + 換 preview ─────────────────
    persisted = maybe_persist_large_tool_result(
        ctx.session_id, tool_use_id, result_text,
    )
    notes: list[str] = []
    if persisted.persisted_path is not None:
        notes.append(
            f"persisted {persisted.persisted_size} bytes to {persisted.persisted_path}"
        )

    # ─── 8. final result update(送給模型的版本可能是 preview)──────────────
    msg = _make_result_message(
        tool_use_id, persisted.content_for_model, is_error=is_error,
    )
    yield ToolResultUpdate(
        tool_use_id=tool_use_id,
        tool_name=tool_name,
        message=msg,
        is_error=is_error,
        extra_notes=notes,
    )
