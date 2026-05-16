"""query_loop — agent 的主迴圈。對應 TS Claude Code `src/query.ts:queryLoop`。

無狀態 generator:給定 provider + messages + tools + canUseTool + hooks,跑完直到
模型不再 emit tool_use 或達到 max_turns。

Provider-agnostic:接受任何 LLMProvider 實作(Phase 0 抽象)。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import anyio

from orion_sdk.compact.auto import auto_compact_if_needed
from orion_sdk.compact.reactive import (
    is_prompt_too_long_error,
    reactive_compact,
)
from orion_sdk.core.abort import abort_aware_scope
from orion_sdk.core.message_cache import compute_message_breakpoints
from orion_sdk.core.state import AgentContext
from orion_sdk.core.streaming_executor import StreamingToolExecutor
from orion_sdk.core.tool import Tool
from orion_sdk.core.tool_execution import (
    ToolProgressUpdate,
    ToolResultUpdate,
    ToolUpdate,
)
from orion_sdk.core.tool_orchestration import run_tools  # noqa: F401 — 留作 fallback / 測試
from orion_sdk.core.transitions import Terminal
from orion_sdk.hooks.registry import HookRegistry
from orion_model.events import (
    MessageStopEvent,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ToolUseStopEvent,
)
from orion_model.provider import LLMProvider, ReasoningEffort
from orion_model.tool_def import ToolDefinition
from orion_model.types import (
    NormalizedMessage,
    TextBlock,
    ToolUseBlock,
)
from orion_sdk.permissions.decisions import CanUseToolFn
from orion_sdk.storage.replacement_state import (
    ContentReplacementState,
    apply_tool_result_budget,
)


@dataclass
class QueryParams:
    """query_loop 的輸入。"""

    provider: LLMProvider
    """LLM provider — Phase 0 抽象,可為 Anthropic / OpenAI。"""

    system_prompt: str | list[str]
    """單字串(簡單模式)或 list[str](Phase 4 cache scope:Anthropic 自動把
    last-1 element 標 cache_control)。Phase 0 LLMProvider.stream 已支援兩種。"""
    tools: list[Tool[Any]]
    can_use_tool: CanUseToolFn
    hooks: HookRegistry

    initial_messages: list[NormalizedMessage] = field(default_factory=list)
    """conversation 起始狀態(通常含 user 的第一則訊息)。"""

    max_turns: int = 30
    max_tokens_per_turn: int = 4096
    reasoning_effort: ReasoningEffort | None = None


# ─── yielded event types ────────────────────────────────────────────────────


@dataclass
class AssistantTextDelta:
    """模型 streaming 文字增量。"""

    text: str


@dataclass
class AssistantThinkingDelta:
    """模型 reasoning streaming 增量。"""

    text: str


@dataclass
class AssistantTurnComplete:
    """本 turn 模型 message 完成(text + tool_use blocks 都收齊)。
    `message` 已 append 到內部 state_messages,**不**需要 caller 再 append。
    """

    message: NormalizedMessage
    stop_reason: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    reasoning_tokens: int = 0


@dataclass
class LoopTerminated:
    """整個 query_loop 結束。"""

    transition: Terminal
    total_turns: int
    final_messages: list[NormalizedMessage]
    """整個 conversation 累積的 messages(含初始 + 各 turn 的 assistant + tool_result)。"""


LoopEvent = (
    AssistantTextDelta
    | AssistantThinkingDelta
    | AssistantTurnComplete
    | ToolUpdate
    | LoopTerminated
)


# ─── main loop ──────────────────────────────────────────────────────────────


def _tool_definitions(tools: list[Tool[Any]]) -> list[ToolDefinition]:
    """把 Tool 列表轉成送給模型的 ToolDefinition 列表。"""
    return [
        ToolDefinition(
            name=t.name,
            description=t.description,
            input_schema=t.input_schema.model_json_schema(),
        )
        for t in tools
    ]


async def _run_one_turn(
    *,
    params: QueryParams,
    ctx: AgentContext,
    state_messages: list[NormalizedMessage],
    tool_defs: list[ToolDefinition],
) -> AsyncIterator[LoopEvent]:
    """跑一輪:stream model + streaming tool execution(立即 add_tool)+ drain。

    順序:
        1. 模型 stream 進來 — text yield、tool_use_stop 立刻送進 executor 開始跑
        2. stream 結束 — 組 assistant NormalizedMessage(text + tool_use blocks)
        3. yield AssistantTurnComplete(message 已 append 到 state_messages)
        4. drain executor — 按 add 順序 yield ToolProgressUpdate / ToolResultUpdate

    Phase 16:整段包進 abort_aware_scope。ctx.abort_event 中途 set 會立即 cancel
    provider.stream 的 httpx connection,本函式提前 return,讓 query_loop 下一輪
    觀察到 abort_event 並 emit Terminal(reason="aborted")。
    """
    text_chunks: list[str] = []
    pending_tool_uses: dict[int, ToolUseBlock] = {}
    stop_reason = "end_turn"
    input_tokens = 0
    output_tokens = 0
    cache_read_tokens = 0
    cache_creation_tokens = 0
    reasoning_tokens = 0

    from orion_sdk.telemetry.instrumentation import record_usage, trace_api_call

    async with abort_aware_scope(ctx.abort_event) as abort_scope:
        async with StreamingToolExecutor(
            params.tools,
            can_use_tool=params.can_use_tool,
            hooks=params.hooks,
            ctx=ctx,
        ) as executor:
            # ─── 1. stream model ────────────────────────────────────────────
            async with trace_api_call(
                model=params.provider.model,
                session_id=str(ctx.session_id),
                provider=params.provider.name,
            ):
                msg_bps = compute_message_breakpoints(state_messages)
                async for ev in params.provider.stream(
                    system=params.system_prompt,
                    messages=state_messages,
                    tools=tool_defs,
                    max_tokens=params.max_tokens_per_turn,
                    reasoning_effort=params.reasoning_effort,
                    cache_breakpoints=msg_bps,
                ):
                    if isinstance(ev, TextDeltaEvent):
                        text_chunks.append(ev.text)
                        yield AssistantTextDelta(text=ev.text)
                    elif isinstance(ev, ThinkingDeltaEvent):
                        yield AssistantThinkingDelta(text=ev.text)
                    elif isinstance(ev, ToolUseStopEvent):
                        block = ToolUseBlock(
                            id=ev.tool_use_id,
                            name=ev.tool_name,
                            input=ev.full_input,
                        )
                        pending_tool_uses[ev.block_index] = block
                        # streaming:模型一 yield tool_use 就立即 add → 可能立刻開跑
                        executor.add_tool(block)
                    elif isinstance(ev, MessageStopEvent):
                        stop_reason = ev.stop_reason
                        input_tokens = ev.usage.input_tokens
                        output_tokens = ev.usage.output_tokens
                        cache_read_tokens = ev.usage.cache_read_tokens
                        cache_creation_tokens = ev.usage.cache_creation_tokens
                        reasoning_tokens = ev.usage.reasoning_tokens

            # Phase 9:把 token usage 寫進 cost tracker + OTel counter
            record_usage(
                session_id=str(ctx.session_id),
                user_id=ctx.user_id,
                model=params.provider.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

            # ─── 2. 組 assistant NormalizedMessage ──────────────────────────
            tool_uses_in_order: list[ToolUseBlock] = [
                pending_tool_uses[idx] for idx in sorted(pending_tool_uses)
            ]
            assistant_blocks: list[Any] = []
            if text_chunks:
                joined = "".join(text_chunks)
                if joined.strip():
                    assistant_blocks.append(TextBlock(text=joined))
            assistant_blocks.extend(tool_uses_in_order)

            # 即使沒任何 block(理論上不該發生),也 append 一個空 text 以維持對齊
            if not assistant_blocks:
                assistant_blocks.append(TextBlock(text=""))

            assistant_msg = NormalizedMessage(role="assistant", content=assistant_blocks)
            state_messages.append(assistant_msg)

            # ─── 3. assistant turn complete ─────────────────────────────────
            yield AssistantTurnComplete(
                message=assistant_msg,
                stop_reason=stop_reason,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_creation_tokens=cache_creation_tokens,
                reasoning_tokens=reasoning_tokens,
            )

            # ─── 4. drain — 工具結果按 add 順序 yield ──────────────────────
            async for upd in executor.drain():
                yield upd

    # 出 abort_aware_scope:若中途被 cancel,直接 return
    # (query_loop 下一輪 abort_event 檢查會 emit Terminal aborted)
    if abort_scope.cancel_called:
        return


async def query_loop(
    params: QueryParams,
    ctx: AgentContext,
) -> AsyncIterator[LoopEvent]:
    """主迴圈。對應 TS query.ts:241 queryLoop。

    while not Terminal:
      ① stream provider → 累積 text + tool_use blocks → AssistantTurnComplete
      ② 若沒 tool_use → Terminal(natural_stop)
      ③ run_tools 執行,把 tool_result 塞回 state_messages
      ④ 下一輪
      ⑤ ctx.abort_event set → Terminal(aborted)
      ⑥ 超 max_turns → Terminal(max_turns_reached)
    """
    state_messages = list(params.initial_messages)
    tool_defs = _tool_definitions(params.tools)
    turn_count = 0
    transition: Terminal | None = None

    while True:
        if ctx.abort_event.is_set():
            transition = Terminal(reason="aborted")
            break

        if turn_count >= params.max_turns:
            transition = Terminal(reason="max_turns_reached")
            break

        turn_count += 1

        # ─── Phase 3: autoCompact(token 接近上限就摘要前段)──────────────
        state_messages, _was_compacted = await auto_compact_if_needed(
            state_messages, provider=params.provider,
        )

        # ─── Phase 2: 第 3 層 budget(進 API 前 aggregate)─────────────────
        if isinstance(ctx.replacement_state, ContentReplacementState):
            state_messages, _decisions = apply_tool_result_budget(
                state_messages,
                ctx.replacement_state,
                ctx.session_id,
            )

        # ─── stream + executor + drain(全部在 _run_one_turn 裡)─────────────
        # Phase 3:catch prompt-too-long → reactive compact + retry once
        last_assistant_msg: NormalizedMessage | None = None
        result_blocks: list[Any] = []
        retried = False

        while True:
            try:
                async for ev in _run_one_turn(
                    params=params,
                    ctx=ctx,
                    state_messages=state_messages,
                    tool_defs=tool_defs,
                ):
                    yield ev
                    if isinstance(ev, AssistantTurnComplete):
                        last_assistant_msg = ev.message
                    elif isinstance(ev, ToolResultUpdate):
                        if isinstance(ev.message.content, list):
                            result_blocks.extend(ev.message.content)
                    elif isinstance(ev, ToolProgressUpdate):
                        pass
                break  # 成功跑完,離開 retry while
            except Exception as e:  # noqa: BLE001
                if retried or not is_prompt_too_long_error(e):
                    raise
                # 第一次撞到 prompt-too-long → reactive compact + retry once
                state_messages = await reactive_compact(
                    state_messages, provider=params.provider,
                )
                # 重置這輪 collected
                last_assistant_msg = None
                result_blocks = []
                retried = True
                continue

        # Phase 16:abort 中途 cancel 會讓 _run_one_turn 提前 return,
        # 此時 last_assistant_msg 仍是 None。先檢查 abort_event 避免誤判 empty_response。
        if ctx.abort_event.is_set():
            transition = Terminal(reason="aborted")
            break

        if last_assistant_msg is None:
            transition = Terminal(reason="empty_response")
            break

        # ─── 收集本輪的 tool_use blocks 決定 continue / terminate ───────────
        tool_uses: list[ToolUseBlock] = [
            b for b in last_assistant_msg.content
            if isinstance(b, ToolUseBlock)
        ] if isinstance(last_assistant_msg.content, list) else []

        if not tool_uses:
            transition = Terminal(reason="natural_stop")
            break

        if ctx.abort_event.is_set():
            transition = Terminal(reason="aborted")
            break

        # 把所有 ToolResultBlock 合成一則 user message(Anthropic 慣例)
        if result_blocks:
            state_messages.append(
                NormalizedMessage(role="user", content=result_blocks)
            )

    yield LoopTerminated(
        transition=transition,
        total_turns=turn_count,
        final_messages=state_messages,
    )
