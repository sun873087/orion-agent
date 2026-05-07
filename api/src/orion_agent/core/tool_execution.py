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

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import ErrorEvent, ProgressEvent, TextEvent, Tool, ToolEvent
from orion_agent.hooks.events import PostToolUseEvent, PreToolUseEvent
from orion_agent.hooks.registry import HookRegistry
from orion_agent.llm.types import NormalizedMessage, ToolResultBlock
from orion_agent.permissions.decisions import (
    CanUseToolFn,
    PermissionDecision,
)
from orion_agent.storage.tool_result import maybe_persist_large_tool_result


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


ToolUpdate = ToolProgressUpdate | ToolResultUpdate


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
    """單一 tool 執行流程,yield ToolProgressUpdate*,最後 yield 一個 ToolResultUpdate。"""

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
        tool=tool, tool_input=raw_input, ctx=ctx,
    )
    pre_allowed = await hooks.pre_tool_use(pre_event)
    if not pre_allowed:
        msg = _make_result_message(
            tool_use_id,
            f"Tool {tool_name!r} blocked by pre_tool_use hook.",
            is_error=True,
        )
        yield ToolResultUpdate(
            tool_use_id=tool_use_id, tool_name=tool_name, message=msg, is_error=True,
        )
        return

    # ─── 4. CanUseToolFn permission ─────────────────────────────────────────
    perm = await can_use_tool(tool, raw_input, ctx)
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

    # ─── 6. PostToolUse hook(看「真實完整」結果,不被 persistence 替換)──────
    post_event = PostToolUseEvent(
        tool=tool,
        tool_input=raw_input,
        result_text=result_text,
        is_error=is_error,
        ctx=ctx,
    )
    await hooks.post_tool_use(post_event)

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
