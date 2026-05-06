"""query_loop — agent 的主迴圈。對應 TS Claude Code `src/query.ts:queryLoop`。

無狀態 generator:給定 provider + messages + tools + canUseTool + hooks,跑完直到
模型不再 emit tool_use 或達到 max_turns。

Provider-agnostic:接受任何 LLMProvider 實作(Phase 0 抽象)。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import Tool
from orion_agent.core.tool_execution import (
    ToolProgressUpdate,
    ToolResultUpdate,
    ToolUpdate,
)
from orion_agent.core.tool_orchestration import run_tools
from orion_agent.core.transitions import Terminal
from orion_agent.hooks.registry import HookRegistry
from orion_agent.llm.events import (
    MessageStopEvent,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ToolUseStopEvent,
)
from orion_agent.llm.provider import LLMProvider, ReasoningEffort
from orion_agent.llm.tool_def import ToolDefinition
from orion_agent.llm.types import (
    NormalizedMessage,
    TextBlock,
    ToolUseBlock,
)
from orion_agent.permissions.decisions import CanUseToolFn


@dataclass
class QueryParams:
    """query_loop 的輸入。"""

    provider: LLMProvider
    """LLM provider — Phase 0 抽象,可為 Anthropic / OpenAI。"""

    system_prompt: str
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
    provider: LLMProvider,
    system_prompt: str,
    state_messages: list[NormalizedMessage],
    tool_defs: list[ToolDefinition],
    max_tokens: int,
    reasoning_effort: ReasoningEffort | None,
) -> AsyncIterator[LoopEvent]:
    """跑一輪 model stream,yield delta events,最後 yield AssistantTurnComplete。

    內部會根據收到的 NormalizedEvent 累積 text + tool_use blocks 成一則 assistant
    NormalizedMessage,並 append 到 state_messages(in-place mutate)。
    """
    text_chunks: list[str] = []
    tool_uses: list[ToolUseBlock] = []
    stop_reason = "end_turn"
    input_tokens = 0
    output_tokens = 0

    # tool_use 暫存:block_index → (id, name, full_input?)
    pending_tool_uses: dict[int, dict[str, Any]] = {}

    async for ev in provider.stream(
        system=system_prompt,
        messages=state_messages,
        tools=tool_defs,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
    ):
        if isinstance(ev, TextDeltaEvent):
            text_chunks.append(ev.text)
            yield AssistantTextDelta(text=ev.text)
        elif isinstance(ev, ThinkingDeltaEvent):
            yield AssistantThinkingDelta(text=ev.text)
        elif isinstance(ev, ToolUseStopEvent):
            pending_tool_uses[ev.block_index] = {
                "id": ev.tool_use_id,
                "name": ev.tool_name,
                "input": ev.full_input,
            }
        elif isinstance(ev, MessageStopEvent):
            stop_reason = ev.stop_reason
            input_tokens = ev.usage.input_tokens
            output_tokens = ev.usage.output_tokens

    # 組 ToolUseBlock(按 block_index 順序)
    for idx in sorted(pending_tool_uses):
        info = pending_tool_uses[idx]
        tool_uses.append(
            ToolUseBlock(id=info["id"], name=info["name"], input=info["input"])
        )

    # 組 assistant NormalizedMessage:text block + tool_use blocks
    assistant_blocks: list[Any] = []
    if text_chunks:
        joined = "".join(text_chunks)
        if joined.strip():
            assistant_blocks.append(TextBlock(text=joined))
    assistant_blocks.extend(tool_uses)

    # 即使沒任何 block(理論上不該發生),也 append 一個空 text 以維持對話對齊
    if not assistant_blocks:
        assistant_blocks.append(TextBlock(text=""))

    assistant_msg = NormalizedMessage(role="assistant", content=assistant_blocks)
    state_messages.append(assistant_msg)

    yield AssistantTurnComplete(
        message=assistant_msg,
        stop_reason=stop_reason,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


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

        # ─── 1. stream model ────────────────────────────────────────────────
        last_assistant_msg: NormalizedMessage | None = None
        async for ev in _run_one_turn(
            provider=params.provider,
            system_prompt=params.system_prompt,
            state_messages=state_messages,
            tool_defs=tool_defs,
            max_tokens=params.max_tokens_per_turn,
            reasoning_effort=params.reasoning_effort,
        ):
            yield ev
            if isinstance(ev, AssistantTurnComplete):
                last_assistant_msg = ev.message

        if last_assistant_msg is None:
            # 不該發生,但保險 — provider 沒給我們任何完整 message,終止避免死循環
            transition = Terminal(reason="empty_response")
            break

        # ─── 2. 收集本輪的 tool_use blocks ──────────────────────────────────
        tool_uses: list[ToolUseBlock] = [
            b for b in last_assistant_msg.content
            if isinstance(b, ToolUseBlock)
        ] if isinstance(last_assistant_msg.content, list) else []

        if not tool_uses:
            transition = Terminal(reason="natural_stop")
            break

        # ─── 3. 跑工具,把結果累積成一則 user NormalizedMessage 回填 ─────────
        result_blocks: list[Any] = []
        async for upd in run_tools(
            tool_uses,
            tools=params.tools,
            can_use_tool=params.can_use_tool,
            hooks=params.hooks,
            ctx=ctx,
        ):
            yield upd
            if isinstance(upd, ToolResultUpdate):
                # upd.message.content 是 [ToolResultBlock(...)]
                if isinstance(upd.message.content, list):
                    result_blocks.extend(upd.message.content)
            elif isinstance(upd, ToolProgressUpdate):
                pass  # progress 已 yield 給 caller,不進 state

            if ctx.abort_event.is_set():
                break

        if ctx.abort_event.is_set():
            transition = Terminal(reason="aborted")
            break

        # 把所有 ToolResultBlock 合成一則 user message(對應 Anthropic 慣例)
        if result_blocks:
            state_messages.append(
                NormalizedMessage(role="user", content=result_blocks)
            )

    yield LoopTerminated(
        transition=transition,
        total_turns=turn_count,
        final_messages=state_messages,
    )
