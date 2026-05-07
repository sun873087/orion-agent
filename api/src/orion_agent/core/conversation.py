"""Conversation — 跨 turn 的高階 wrapper。對應 TS Claude Code QueryEngine 的部分職責。

Phase 1 範圍:provider / tools / permission / hooks / state_messages / stats。
Phase 2 加入:JSONL transcript persistence + ContentReplacementState 共用 +
            Conversation.resume(session_id) 重建。

使用範例:
    conv = Conversation(provider=p, system_prompt="...", tools=[...])
    async for ev in conv.send("Read /etc/hosts"):
        ...
    # session_id = conv.session_id;之後可 resume 同一條
    later = await Conversation.resume(conv.session_id, provider=p, tools=[...])
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from orion_agent.core.query_loop import (
    AssistantTurnComplete,
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
from orion_agent.memory.extract import extract_memories
from orion_agent.memory.paths import default_user_id, user_memory_paths
from orion_agent.memory.scan import scan_memory_dir
from orion_agent.permissions.decisions import (
    CanUseToolFn,
    always_allow,
)
from orion_agent.prompt.assembler import (
    build_system_prompt_list,
    fetch_system_prompt_parts,
)
from orion_agent.storage.replacement_state import ContentReplacementState
from orion_agent.storage.session import SessionStorage


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
    """跨 send() 共用的 agent 對話狀態。"""

    provider: LLMProvider
    system_prompt: str = ""
    """**Phase 4**:可省略;不傳 → Conversation 自己用 prompt/static_sections + 動態段組裝。
    傳了 → 視為 caller 客製,完整覆蓋(不再加靜態 7 段)。"""
    tools: list[Tool[Any]] = field(default_factory=list)
    can_use_tool: CanUseToolFn = always_allow
    hooks: HookRegistry = field(default_factory=HookRegistry)
    max_turns: int = 30
    max_tokens_per_turn: int = 4096
    reasoning_effort: ReasoningEffort | None = None

    state_messages: list[NormalizedMessage] = field(default_factory=list)
    """整條 conversation 的訊息歷史。每次 send() 後會追加新內容。"""

    stats: ConversationStats = field(default_factory=ConversationStats)

    # ─── Phase 2 ──────────────────────────────────────────────────────────
    session_id: UUID = field(default_factory=uuid4)
    """conversation 的唯一 ID。Resume 時用此 ID 找 transcript。"""

    persistence_enabled: bool = True
    """True → 每 turn 寫 JSONL transcript + 啟用 layer-3 budget。
    測試 / 子 agent 通常設 False(避免 disk I/O)。"""

    replacement_state: ContentReplacementState = field(default_factory=ContentReplacementState)
    """Phase 2 第 3 層 budget 的決策歷史。跨 turn 累積,resume 時從 transcript 重建。"""

    _session_storage: SessionStorage | None = None
    """SessionStorage instance,lazy init 在第一次 send() 時。"""

    # ─── Phase 3 ──────────────────────────────────────────────────────────
    user_id: str = field(default_factory=default_user_id)
    """Per-user memory key。CLI 預設 "default";Phase 6 web app 透過 session 注入。"""

    memory_enabled: bool = True
    """True → send() 前載入相關 memory 進 system prompt;LoopTerminated 時 fork 萃取。"""

    auto_extract_memories: bool = True
    """True → 對話結束 fork 子 agent 萃取 memory(失敗不影響主對話)。"""

    async def send(
        self,
        user_text: str,
        ctx: AgentContext | None = None,
    ) -> AsyncIterator[LoopEvent]:
        """送一則 user 訊息,跑 query_loop 直到 terminate,yield events。"""
        if ctx is None:
            ctx = AgentContext(session_id=self.session_id, user_id=self.user_id)
        else:
            # 確保 ctx 用 conversation 的 session_id / user_id
            ctx.session_id = self.session_id
            ctx.user_id = self.user_id

        # 共用 replacement_state(query_loop 會用 ctx.replacement_state)
        if self.persistence_enabled:
            ctx.replacement_state = self.replacement_state

        # 延遲 init storage(避免測試強制建檔案)
        store = await self._ensure_storage()

        # user 訊息進 state + 寫 transcript
        user_msg = NormalizedMessage(role="user", content=user_text)
        self.state_messages.append(user_msg)
        if store is not None:
            await store.record_message(user_msg)

        # ─── Phase 4:組裝 system prompt(7 段靜態 + 動態 + memory)──────────
        effective_system_prompt: str | list[str]
        if self.system_prompt:
            # caller 給了完整 prompt → 直接用(向後相容,且 memory 仍會載入動態段)
            effective_system_prompt = self.system_prompt
        else:
            try:
                parts = await fetch_system_prompt_parts(
                    cwd=ctx.cwd,
                    user_id=self.user_id,
                    conversation_messages=self.state_messages,
                    provider=self.provider if self.memory_enabled else None,
                )
                effective_system_prompt = build_system_prompt_list(parts)
            except Exception:  # noqa: BLE001 — fallback 到純靜態 block
                from orion_agent.prompt.static_sections import render_static_block
                effective_system_prompt = render_static_block()

        params = QueryParams(
            provider=self.provider,
            system_prompt=effective_system_prompt,
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
            if isinstance(ev, AssistantTurnComplete):
                self.stats.input_tokens += ev.input_tokens
                self.stats.output_tokens += ev.output_tokens
                if store is not None:
                    await store.record_message(ev.message)
            elif isinstance(ev, ToolResultUpdate):
                self.stats.tool_calls += 1
                if ev.is_error:
                    self.stats.tool_errors += 1
                if ev.extra_notes and any("not permitted" in n for n in ev.extra_notes):
                    self.stats.permission_denials += 1
                # 工具結果 message 也寫 transcript(供 resume)
                if store is not None:
                    await store.record_message(ev.message)
            elif isinstance(ev, LoopTerminated):
                self.stats.turns += ev.total_turns
                self.state_messages = ev.final_messages
                if store is not None:
                    await store.record_transition(
                        reason=ev.transition.reason,
                        total_turns=ev.total_turns,
                    )

                # ─── Phase 3:fork 子 agent 萃取新 memory(失敗不影響)───────
                if self.memory_enabled and self.auto_extract_memories:
                    try:
                        paths = user_memory_paths(self.user_id)
                        existing = scan_memory_dir(paths).memories
                        await extract_memories(
                            self.state_messages,
                            existing,
                            provider=self.provider,
                            paths=paths,
                        )
                    except Exception:  # noqa: BLE001
                        pass  # 萃取失敗不該炸對話

    async def _ensure_storage(self) -> SessionStorage | None:
        """Lazy 初始化 SessionStorage。"""
        if not self.persistence_enabled:
            return None
        if self._session_storage is None:
            store = SessionStorage.open(self.session_id)
            await store.record_meta(
                provider=self.provider.name,
                model=self.provider.model,
                system_prompt=self.system_prompt,
            )
            self._session_storage = store
        return self._session_storage

    @classmethod
    async def resume(
        cls,
        session_id: UUID,
        *,
        provider: LLMProvider,
        tools: list[Tool[Any]],
        system_prompt: str | None = None,
        can_use_tool: CanUseToolFn = always_allow,
        hooks: HookRegistry | None = None,
        max_turns: int = 30,
    ) -> Conversation:
        """從既有 session 載入 transcript,重建 Conversation。

        Args:
            session_id: 之前 conversation 的 session_id
            provider / tools / system_prompt / ...: 同 __init__,system_prompt 若 None
                會試著從 transcript 的 session-meta record 取出。

        Returns:
            Conversation 實例,state_messages + replacement_state 已重建。
        """
        import sys

        from orion_agent.storage.resume import load_session

        snapshot = load_session(session_id)
        sp_text = system_prompt or snapshot.system_prompt or ""

        # Dangling tool_use auto-repair 等警告(若有)印到 stderr
        for w in snapshot.warnings:
            print(f"[resume warning] {w}", file=sys.stderr, flush=True)

        conv = cls(
            provider=provider,
            system_prompt=sp_text,
            tools=tools,
            can_use_tool=can_use_tool,
            hooks=hooks or HookRegistry(),
            max_turns=max_turns,
            session_id=session_id,
            state_messages=snapshot.messages,
            replacement_state=snapshot.replacement_state,
        )
        return conv
