"""AgentTool — spawn 子 agent 跑 query_loop。

對應 TS Claude Code `src/tools/AgentTool/`。

設計:
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

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, Tool, ToolEvent, ToolInput
from orion_sdk.hooks.registry import HookRegistry
from orion_model.provider import LLMProvider
from orion_sdk.permissions.decisions import always_allow

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
        parent_hooks: HookRegistry | None = None,
        sandbox_factory: object | None = None,
    ) -> None:
        self.provider = provider
        # 過濾掉自己,防止 child_tools 含 AgentTool 造成 deeper spawn
        self.child_tools = [t for t in child_tools if t.name != self.name]
        self.max_child_turns = max_child_turns
        # parent 的 hook registry(用來 fire SubagentStart),子 agent 自己不繼承
        self.parent_hooks = parent_hooks
        # 給子 agent 新 sandbox 的 factory(同步 / async 都吃)。
        # None → 子共用父 sandbox(若父有);否則無 sandbox。
        self.sandbox_factory = sandbox_factory

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

        # 走 services.forked_agent 統一 fork 入口(cache-safe params 抽象)
        from orion_sdk.services.forked_agent import (
            CacheSafeParams,
            run_forked_agent,
        )

        cache_safe = CacheSafeParams.from_parts(
            system_prompt=_SUB_AGENT_SYSTEM_PROMPT,
            tools=self.child_tools,
            messages=[], # 子 agent 從空對話起跑(獨立 system + 自己的 task）
        )

        # SubagentStart hook 仍在 parent registry 上 fire(forked_agent 內部不繼承)
        new_session_str: str | None = None
        if self.parent_hooks is not None:
            from uuid import uuid4

            from orion_sdk.hooks.events import SubagentStartEvent

            # 預先生成 session id 以塞 hook(forked_agent 內部會新建,這裡只給 hook event)
            new_session_str = str(uuid4())
            await self.parent_hooks.fire(
                SubagentStartEvent(
                    parent_session_id=str(ctx.session_id),
                    subagent_type=self.name,
                    prompt=input.task,
                    ctx=ctx,
                    session_id=new_session_str,
                    user_id=ctx.user_id,
                ),
            )

        try:
            result = await run_forked_agent(
                parent_ctx=ctx,
                parent_params=cache_safe,
                user_prompt=input.task,
                provider=self.provider,
                can_use_tool=always_allow,
                max_turns=self.max_child_turns,
                fork_label="agent_tool",
                sandbox_factory=self.sandbox_factory, # type: ignore[arg-type]
                inherit_sandbox=(
                    self.sandbox_factory is None and ctx.sandbox_backend is not None
                ),
            )
        except Exception as e: # noqa: BLE001
            yield ErrorEvent(message=f"sub-agent crashed: {type(e).__name__}: {e}")
            return

        final_text = result.final_text.strip()
        if not final_text:
            yield TextEvent(text="(sub-agent finished but produced no final text)")
        else:
            yield TextEvent(text=final_text)

    def is_concurrency_safe(self, input: AgentToolInput) -> bool: # noqa: ARG002
        # 子 agent 內部會跑工具;為避免複雜資源競爭,本 tool 不並發
        return False

    def is_read_only(self, input: AgentToolInput) -> bool: # noqa: ARG002
        # 子 agent 可能 write/edit/bash,保守 False
        return False

    def max_result_size_chars(self) -> int | float:
        return 50_000
