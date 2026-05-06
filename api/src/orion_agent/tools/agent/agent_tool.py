"""AgentTool — spawn 子 agent 跑 query_loop。

對應 TS Claude Code `src/tools/AgentTool/`。

Phase 1 設計:
- 共用 parent 的 LLMProvider(省 client config 重建)
- 獨立 AgentContext(獨立 abort_event、token_budget、sub_agent_depth+1)
- child_tools 由 caller 傳入(通常是不含 AgentTool 自己)
- 深度限制:sub_agent_depth >= 1 不能再 spawn(防無限遞迴)
- max_turns 預設 10(比 main 30 小)
- 只回 final assistant text 給 parent — 中間 streaming 不外露
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from pydantic import Field

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import ErrorEvent, TextEvent, Tool, ToolEvent, ToolInput
from orion_agent.hooks.registry import HookRegistry
from orion_agent.llm.provider import LLMProvider
from orion_agent.permissions.decisions import always_allow

_SUB_AGENT_SYSTEM_PROMPT = """\
You are a focused sub-agent invoked by a parent agent. Complete the assigned task
using the tools available. Be concise. Return only the final answer, not your
reasoning trace. You cannot spawn further sub-agents.\
"""


class AgentToolInput(ToolInput):
    """AgentTool 的 input。"""

    task: str = Field(
        ...,
        description="The task description for the sub-agent. Be specific — the sub-agent has no parent context.",
    )


class AgentTool:
    name = "Agent"
    description = (
        "Spawn a focused sub-agent to handle a self-contained task. "
        "Use for parallel exploration, isolated context, or when the task needs many tool calls "
        "you don't want polluting the main conversation. The sub-agent returns only its final answer."
    )
    input_schema = AgentToolInput

    def __init__(
        self,
        provider: LLMProvider,
        child_tools: list[Tool[Any]],
        max_child_turns: int = 10,
    ) -> None:
        self.provider = provider
        # 過濾掉自己,防止 child_tools 含 AgentTool 造成 deeper spawn
        self.child_tools = [t for t in child_tools if t.name != self.name]
        self.max_child_turns = max_child_turns

    async def call(
        self,
        input: AgentToolInput,
        ctx: AgentContext,
    ) -> AsyncIterator[ToolEvent]:
        if ctx.sub_agent_depth >= 1:
            yield ErrorEvent(
                message="AgentTool cannot be nested — sub-agents may not spawn further sub-agents."
            )
            return

        # 延遲 import 避免循環依賴(query_loop 不該是 tool 的 hard dep)
        from orion_agent.core.query_loop import (
            AssistantTextDelta,
            QueryParams,
            query_loop,
        )
        from orion_agent.llm.types import NormalizedMessage

        child_ctx = AgentContext(
            cwd=ctx.cwd,
            feature_flags=dict(ctx.feature_flags),
            sub_agent_depth=ctx.sub_agent_depth + 1,
        )

        params = QueryParams(
            provider=self.provider,
            system_prompt=_SUB_AGENT_SYSTEM_PROMPT,
            tools=self.child_tools,
            can_use_tool=always_allow,  # 子 agent 不再問 permission(parent 已同意)
            hooks=HookRegistry(),
            initial_messages=[
                NormalizedMessage(role="user", content=input.task),
            ],
            max_turns=self.max_child_turns,
        )

        text_chunks: list[str] = []
        try:
            async for ev in query_loop(params, child_ctx):
                if isinstance(ev, AssistantTextDelta):
                    text_chunks.append(ev.text)
                # 不 propagate 子 agent 內部 tool 事件給 parent — 純 black box
        except Exception as e:  # noqa: BLE001
            yield ErrorEvent(message=f"sub-agent crashed: {type(e).__name__}: {e}")
            return

        final_text = "".join(text_chunks).strip()
        if not final_text:
            yield TextEvent(text="(sub-agent finished but produced no final text)")
        else:
            yield TextEvent(text=final_text)

    def is_concurrency_safe(self, input: AgentToolInput) -> bool:  # noqa: ARG002
        # 子 agent 內部會跑工具;為避免複雜資源競爭,本 tool 不並發
        return False

    def is_read_only(self, input: AgentToolInput) -> bool:  # noqa: ARG002
        # 子 agent 可能 write/edit/bash,保守 False
        return False

    def max_result_size_chars(self) -> int | float:
        return 50_000
