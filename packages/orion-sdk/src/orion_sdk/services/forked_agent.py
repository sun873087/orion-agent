"""forked_agent — 共享父 prompt cache 的 fork agent。

對應 TS Claude Code `src/utils/forkedAgent.ts`。Phase 12。

關鍵概念:**byte-identical prefix → Anthropic prompt cache 命中**。

`CacheSafeParams` 在 fork 時把父對話的「快取相關前綴」(system + tools + messages)
複製成 immutable snapshot;之後父對話繼續走、修改 self.state_messages,fork 拿到的
副本不受影響,進 LLM 時前綴仍與父先前那次 turn 相同 → 命中 cache。

caller 範例:
- Phase 3 `extract_memories`(背景萃取,不影響主對話)
- Phase 1 `AgentTool.call`(spawn 子 agent)
- 任何「跑一段子流程但要省 token」的場景

設計:
- 沿用 Phase 9 `fork_context_for_subagent`(獨立 abort / sandbox / sub_agent_depth+1)
- 新 HookRegistry(fork **不繼承** 父 hook,避免重複觸發)
- skip_transcript=True 預設 — fork 不寫 SessionStorage(對應 TS skipTranscript)
- 結果包 `ForkedAgentResult`:final messages、累積 usage、寫過的檔案路徑
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import Tool
from orion_sdk.hooks.registry import HookRegistry
from orion_model.provider import LLMProvider
from orion_model.types import NormalizedMessage, ToolUseBlock
from orion_sdk.permissions.decisions import CanUseToolFn, always_allow
from orion_sdk.sandbox.sub_agent_isolation import (
    SandboxFactory,
    fork_context_for_subagent,
    release_subagent,
)


@dataclass
class CacheSafeParams:
    """快取安全的不可變參數包。

    在 fork 時 capture,後續修改父狀態不會破壞 fork 已 capture 的 prefix。
    """

    system_prompt: str | list[str]
    """父對話最後一次 turn 用的 system prompt。**捕獲後不可變動**。"""

    tools: list[Tool[Any]]
    """父對話的 tools list(immutable snapshot)。注意:Tool instance 本身可能還是
    mutable;Phase 12 範圍內信任 tool 不會在 fork 期間改自身 schema。"""

    messages_prefix: list[NormalizedMessage]
    """父對話到 fork 前的訊息歷史(deep enough copy 避免 mutate)。"""

    @classmethod
    def from_parts(
        cls,
        *,
        system_prompt: str | list[str],
        tools: list[Tool[Any]],
        messages: list[NormalizedMessage],
    ) -> CacheSafeParams:
        """從零組件建一個 cache-safe snapshot。

        list 透過 `list(...)` 淺拷貝即可:caller 之後 `.append()` 不會影響本副本。
        Pydantic NormalizedMessage 是值物件,不需 deep copy。
        """
        return cls(
            system_prompt=(
                list(system_prompt) if isinstance(system_prompt, list) else system_prompt
            ),
            tools=list(tools),
            messages_prefix=list(messages),
        )


@dataclass
class ForkedAgentResult:
    """fork 跑完的結果。"""

    final_messages: list[NormalizedMessage]
    """fork 結束時的完整訊息歷史(含父 prefix + fork 自己跑出來的)。"""

    final_text: str
    """fork 最後一個 assistant turn 的純文字輸出(便利欄位,等同從
    final_messages 末段抽出)。"""

    total_usage: dict[str, int]
    """累積 token usage:input_tokens / output_tokens / cache_read_tokens。
    cache_read_tokens > 0 才表示 cache 真的命中。"""

    written_paths: list[str] = field(default_factory=list)
    """fork 期間 Edit / Write 工具寫過的檔案路徑(供 caller decide 是否要 propagate)。"""

    transition_reason: str = ""
    """fork 結束的 transition reason(natural_stop / max_turns_reached / aborted)。"""


async def run_forked_agent(
    *,
    parent_ctx: AgentContext,
    parent_params: CacheSafeParams,
    user_prompt: str,
    provider: LLMProvider,
    can_use_tool: CanUseToolFn = always_allow,
    max_turns: int = 5,
    fork_label: str = "fork",  # noqa: ARG001  ─ 預留供未來 telemetry tag
    sandbox_factory: SandboxFactory | None = None,
    inherit_sandbox: bool = False,
) -> ForkedAgentResult:
    """跑 fork agent。

    與父 **共享 prompt cache 前綴**(system + tools + messages_prefix);fork 在 prefix
    後追加 `user_prompt`,跑 query_loop 直到自然結束 / max_turns。

    Args:
        parent_ctx: 父 AgentContext。
        parent_params: cache-safe snapshot(由 CacheSafeParams.from_parts 建立)。
        user_prompt: fork 的 task 描述(會作為新 user message 加到 prefix 後)。
        provider: LLMProvider(通常與父同一個 instance)。
        can_use_tool: permission policy。預設 always_allow(子 agent 信任父決策)。
        max_turns: fork 最大 turn 數,通常比主對話小。
        sandbox_factory / inherit_sandbox: 同 fork_context_for_subagent。

    Returns:
        ForkedAgentResult(final_messages / final_text / total_usage / written_paths)。
    """
    # 延遲 import 避免循環依賴
    from orion_sdk.core.query_loop import (
        AssistantTextDelta,
        AssistantTurnComplete,
        LoopTerminated,
        QueryParams,
        query_loop,
    )

    handle = await fork_context_for_subagent(
        parent_ctx,
        sandbox_factory=sandbox_factory,
        inherit_sandbox=inherit_sandbox,
    )
    fork_ctx = handle.ctx

    # fork prefix + 新 user message(這是 cache miss 的唯一新內容)
    fork_messages: list[NormalizedMessage] = [
        *parent_params.messages_prefix,
        NormalizedMessage(role="user", content=user_prompt),
    ]

    params = QueryParams(
        provider=provider,
        system_prompt=parent_params.system_prompt,
        tools=parent_params.tools,
        can_use_tool=can_use_tool,
        hooks=HookRegistry(),  # fork 不繼承父 hook,避免重複觸發 SessionStart 等
        initial_messages=fork_messages,
        max_turns=max_turns,
    )

    last_turn_text: list[str] = []
    final_messages: list[NormalizedMessage] = []
    written: list[str] = []
    transition_reason = ""
    total_in = 0
    total_out = 0
    total_cache_read = 0

    try:
        async for ev in query_loop(params, fork_ctx):
            if isinstance(ev, AssistantTextDelta):
                # 累計到「最近一輪」的 text;每次 AssistantTurnComplete 重置
                last_turn_text.append(ev.text)
            elif isinstance(ev, AssistantTurnComplete):
                total_in += ev.input_tokens
                total_out += ev.output_tokens
                # 萃 written paths(若這輪有 Edit / Write tool_use)
                written.extend(_extract_written_paths(ev.message))
                # 把 last_turn_text 收 ≤ 真正的 final 文字輸出在最後一輪
            elif isinstance(ev, LoopTerminated):
                final_messages = ev.final_messages
                transition_reason = ev.transition.reason
    finally:
        await release_subagent(handle)

    # 從 final_messages 倒著抓最末 assistant text(更穩,不依賴 streaming order)
    final_text = _last_assistant_text(final_messages)

    return ForkedAgentResult(
        final_messages=final_messages,
        final_text=final_text,
        total_usage={
            "input_tokens": total_in,
            "output_tokens": total_out,
            "cache_read_tokens": total_cache_read,
        },
        written_paths=written,
        transition_reason=transition_reason,
    )


def _extract_written_paths(message: NormalizedMessage) -> list[str]:
    """從 assistant 訊息抽 Edit / Write tool_use 的 file_path / path 欄位。"""
    if not isinstance(message.content, list):
        return []
    out: list[str] = []
    for block in message.content:
        if not isinstance(block, ToolUseBlock):
            continue
        if block.name not in ("Edit", "Write", "NotebookEdit"):
            continue
        # 工具用 path / file_path 兩種欄位
        path = block.input.get("path") or block.input.get("file_path")
        if isinstance(path, str):
            out.append(path)
    return out


def _last_assistant_text(messages: list[NormalizedMessage]) -> str:
    """倒著找最末 assistant message,串接其 TextBlock。"""
    from orion_model.types import TextBlock

    for m in reversed(messages):
        if m.role != "assistant":
            continue
        if isinstance(m.content, str):
            return m.content
        parts: list[str] = []
        for block in m.content:
            if isinstance(block, TextBlock):
                parts.append(block.text)
        if parts:
            return "".join(parts)
    return ""


# 型別別名:給 caller 用 — fork callable 可以注入(測試)
ForkedAgentRunner = Callable[..., Any]


__all__ = [
    "CacheSafeParams",
    "ForkedAgentResult",
    "ForkedAgentRunner",
    "run_forked_agent",
]
