"""Conversation — 跨 turn 的高階 wrapper。對應 TS Claude Code QueryEngine 的部分職責。

Phase 1 範圍:
- 持有 system prompt、tools、provider、permission policy、hooks
- 累積 messages(state_messages)— 每次 send() 都繼續同一條 conversation
- 提供簡單 send(user_text) 介面跑 agent loop
- 累積 permission_denials / tool_call 計數(供 telemetry)

Phase 2 會加 persistence(transcript / resume),Phase 3 會加 compaction。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from orion_agent.core.query_loop import (
    LoopEvent,
    LoopTerminated,
    QueryParams,
    query_loop,
)
from orion_agent.core.state import AgentContext
from orion_agent.core.tool import Tool
from orion_agent.core.tool_execution import ToolResultUpdate
from orion_agent.hooks.registry import HookRegistry
from orion_agent.llm.provider import LLMProvider, ReasoningEffort
from orion_agent.llm.types import NormalizedMessage
from orion_agent.permissions.decisions import (
    CanUseToolFn,
    always_allow,
)


@dataclass
class ConversationStats:
    """累積統計,給 telemetry / cost tracking。"""

    turns: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    permission_denials: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class Conversation:
    """跨 send() 共用的 agent 對話狀態。

    使用範例:
        conv = Conversation(provider=p, system_prompt="...", tools=[...])
        async for ev in conv.send("Read /etc/hosts"):
            ...
        async for ev in conv.send("now grep for localhost"):  # 同條 conversation
            ...
    """

    provider: LLMProvider
    system_prompt: str
    tools: list[Tool[Any]]
    can_use_tool: CanUseToolFn = always_allow
    hooks: HookRegistry = field(default_factory=HookRegistry)
    max_turns: int = 30
    max_tokens_per_turn: int = 4096
    reasoning_effort: ReasoningEffort | None = None

    state_messages: list[NormalizedMessage] = field(default_factory=list)
    """整條 conversation 的訊息歷史。每次 send() 後會追加新內容。"""

    stats: ConversationStats = field(default_factory=ConversationStats)

    async def send(
        self,
        user_text: str,
        ctx: AgentContext | None = None,
    ) -> AsyncIterator[LoopEvent]:
        """送一則 user 訊息,跑 query_loop 直到 terminate,yield events。"""
        if ctx is None:
            ctx = AgentContext()

        self.state_messages.append(
            NormalizedMessage(role="user", content=user_text)
        )

        params = QueryParams(
            provider=self.provider,
            system_prompt=self.system_prompt,
            tools=self.tools,
            can_use_tool=self.can_use_tool,
            hooks=self.hooks,
            initial_messages=self.state_messages,
            max_turns=self.max_turns,
            max_tokens_per_turn=self.max_tokens_per_turn,
            reasoning_effort=self.reasoning_effort,
        )

        async for ev in query_loop(params, ctx):
            yield ev

            # 累積 stats
            if isinstance(ev, ToolResultUpdate):
                self.stats.tool_calls += 1
                if ev.is_error:
                    self.stats.tool_errors += 1
                if ev.extra_notes and any("not permitted" in n for n in ev.extra_notes):
                    self.stats.permission_denials += 1
            elif isinstance(ev, LoopTerminated):
                self.stats.turns += ev.total_turns
                # 替換 state_messages 為 loop 結束時的版本(含本次 turn 的全部更新)
                self.state_messages = ev.final_messages
