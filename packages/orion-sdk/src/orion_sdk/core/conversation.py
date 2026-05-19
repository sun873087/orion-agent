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

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from orion_sdk.core.query_loop import (
    AssistantTurnComplete,
    LoopEvent,
    LoopTerminated,
    QueryParams,
    query_loop,
)
from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import Tool
from orion_sdk.core.tool_execution import ToolResultUpdate
from orion_sdk.core.transitions import Terminal
from orion_sdk.hooks.registry import HookRegistry
from orion_model.provider import LLMProvider, ReasoningEffort
from orion_model.types import NormalizedMessage
from orion_sdk.memory.extract import extract_memories
from orion_sdk.memory.paths import default_user_id, user_memory_paths
from orion_sdk.memory.scan import scan_memory_dir
from orion_sdk.permissions.decisions import (
    CanUseToolFn,
    always_allow,
)
from orion_sdk.prompt.assembler import (
    build_system_prompt_list,
    fetch_system_prompt_parts,
)
from orion_sdk.storage.replacement_state import ContentReplacementState
from orion_sdk.storage.session import SessionStorage

_log = logging.getLogger(__name__)

_DEFAULT_MAX_TOKENS_PER_TURN = 16384


def _env_max_tokens_per_turn() -> int | None:
    """讀 ORION_MAX_TOKENS_PER_TURN env;非正整數 / 不存在 → None(讓 caller fallback)。"""
    raw = os.environ.get("ORION_MAX_TOKENS_PER_TURN")
    if not raw:
        return None
    try:
        n = int(raw)
        if n < 1:
            raise ValueError
        return n
    except (TypeError, ValueError):
        _log.warning(
            "ORION_MAX_TOKENS_PER_TURN=%r invalid, falling back",
            raw,
        )
        return None


def _default_max_tokens_per_turn() -> int:
    """無 (provider, model) 上下文時的預設值。

    Conversation dataclass 用 — 例如 CLI / 測試直接 `Conversation(provider=...)` 沒設這欄。
    Web chat 走 `pick_max_tokens_per_turn(provider, model)`,可以從 catalog 拿到 per-model 上限。

    優先 env override(可能超過某 model 上限,讓 caller 自己 cap),否則用內建 16384。
    """
    return _env_max_tokens_per_turn() or _DEFAULT_MAX_TOKENS_PER_TURN


def pick_max_tokens_per_turn(provider: str, model: str) -> int:
    """根據 (provider, model) 從 catalog 拿 max_output_tokens;ORION_MAX_TOKENS_PER_TURN 為硬下限/上限封頂。

    規則:
    - env 沒設 → 用 catalog.get_max_output_tokens(),catalog 不認識 → fallback 16384
    - env 有設 → 用 env 值,但 cap 在該 model 的 catalog 上限(避免 API 422)
    """
    # 延遲 import 避開循環(catalog 不依賴 conversation,沒實際循環,但保一致)
    from orion_model.catalog import get_max_output_tokens

    model_max = get_max_output_tokens(provider, model) or _DEFAULT_MAX_TOKENS_PER_TURN
    env = _env_max_tokens_per_turn()
    if env is None:
        return model_max
    return min(env, model_max)


@dataclass
class CompactResult:
    """Conversation.compact() 的回傳結果。"""

    was_compacted: bool
    """True → state_messages 已被替換為含 TombstoneBlock 的新版。
    False → 沒到 threshold(auto 模式)或 messages 太少,沒做事。"""

    summary: str
    """LLM 摘要文字。was_compacted=False 時為空字串。"""

    before_tokens: int
    """被壓縮段落的概略 token 數。was_compacted=False 時為 0。"""

    after_tokens: int
    """壓縮後整個 state_messages 的概略 token 數(僅 was_compacted=True 時計)。"""

    kept_message_count: int
    """壓縮後 state_messages 的長度(含 tombstone 那一張)。"""


@dataclass
class ConversationStats:
    """累積統計,給 telemetry / cost tracking。"""

    turns: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    permission_denials: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    reasoning_tokens: int = 0
    # Last turn 用量(讓 UI 顯「本次對話」vs「session 累積」)
    last_input_tokens: int = 0
    last_output_tokens: int = 0
    last_cache_read_tokens: int = 0
    last_cache_creation_tokens: int = 0
    last_reasoning_tokens: int = 0


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
    max_tokens_per_turn: int = field(default_factory=_default_max_tokens_per_turn)
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

    _pending_extract_tasks: set[asyncio.Task[None]] = field(
        default_factory=set, init=False, repr=False, compare=False,
    )
    """In-flight memory-extract tasks。Strong ref 防 GC,done callback 自動 discard。"""

    # ─── Phase 3 ──────────────────────────────────────────────────────────
    user_id: str = field(default_factory=default_user_id)
    """Per-user memory key。CLI 預設 "default";Phase 6 web app 透過 session 注入。"""

    memory_enabled: bool = True
    """True → send() 前載入相關 memory 進 system prompt;LoopTerminated 時 fork 萃取。"""

    auto_extract_memories: bool = True
    """True → 對話結束 fork 子 agent 萃取 memory(失敗不影響主對話)。"""

    memory_dir_override: "Path | None" = None
    """若給定,extract 寫入這個目錄而非 user_memory_paths(user_id).memory_dir。
    Cowork project chat 用此 override 把 memory 寫到 <workspace>/.orion/memory/。
    """

    include_workspace_context: bool = True
    """True → 帶入 cwd-derived 內容(git_status、`<cwd>/.orion/instructions.md`、
    env_info 內 cwd 顯示)。CLI 預設 True;chat / desktop app 沒「user 工作目錄」
    概念,應傳 False 避免把 process cwd / 啟動 repo git log 注入 prompt。"""

    include_env_info: bool = True
    """True → 帶 platform / date(跟 cwd 無關)。chat / desktop app 通常保 True
    讓模型給對的 OS 命令(open vs xdg-open)。"""

    # ─── Phase 5 ──────────────────────────────────────────────────────────
    mcp_manager: object | None = None
    """McpManager instance(用 object 型別避免循環 import)。
    main / caller 在 async with McpManager(...) 內建 conversation,本欄位指該 manager。
    None → 不啟用 MCP(只用內建工具)。"""

    # ─── Phase 7 ──────────────────────────────────────────────────────────
    sandbox_backend: object | None = None
    """SandboxBackend instance。若有,send() 會傳給 ctx,工具可透過它跑命令。
    self.tools 是否已是 sandboxed proxy 由 caller 決定(main.py 看 --sandbox flag)。
    None = 工具直接動 host(Phase 1-6 行為)。"""

    # ─── Phase 8 ──────────────────────────────────────────────────────────
    _session_started: bool = field(default=False, init=False)
    """SessionStart hook 已觸發過(避免重 fire)。"""

    # ─── Phase 12 ─────────────────────────────────────────────────────────
    file_state_cache: object | None = None
    """FileStateCache instance(避免循環 import)。Conversation 級共用,跨 turn 持久。
    None → lazy 初始化(第一次 send 時建)。"""

    # ─── Phase 13 ─────────────────────────────────────────────────────────
    custom_instructions_user: str | None = None
    """User-level custom instructions(Web chat 模式 — caller 從 DB 讀好塞進來)。
    None → 不加進 system prompt。"""

    custom_instructions_conversation: str | None = None
    """Conversation-level custom instructions。同上。"""

    output_style: str | None = None
    """選用的 output style 名(從 `output-styles/<name>.md` 載)。
    `/output-style <name>` 命令會 mutate 此欄位。"""

    auto_compact_threshold: float | None = None
    """Auto-compact 觸發比例(0.1~0.99)。None → 用 ORION_AUTO_COMPACT_THRESHOLD
    env 或預設 0.8。Cowork sidecar 把使用者設定值寫進來。"""

    compact_summary_locale: str | None = None
    """摘要要用的語系(zh-TW / zh-CN / ja / en)。None → 英文。Cowork sidecar
    從 user UI locale 傳進來,讓摘要 card 跟使用者母語一致。"""

    compact_summary_provider: LLMProvider | None = None
    """摘要要用的 provider override。None → 用 self.provider(跟對話同一個 model)。
    Caller(例如 Cowork sidecar)可注入一個便宜模型的 provider(Haiku /
    gpt-5-mini 等),把每次壓縮的 LLM cost 降到 1/5~1/10。"""

    # ─── Phase 27 ─────────────────────────────────────────────────────────
    db_engine: object | None = None
    """AsyncEngine instance(避免循環 import,object 型別)。
    DbSessionManager 建立 / resume Conversation 時注入;SessionStorage 拿到後
    每筆 record_message 會 dual-write 進 messages 表。
    None → 純 JSONL(CLI 預設、in-memory SessionManager)。"""

    async def send(
        self,
        user_text: str,
        ctx: AgentContext | None = None,
        *,
        images: "list[Any] | None" = None,
    ) -> AsyncIterator[LoopEvent]:
        """送一則 user 訊息,跑 query_loop 直到 terminate,yield events。

        `images`:可選,list of `orion_model.types.ImageBlock`。若有,user message
        會用 list[ContentBlock] 形式儲存([TextBlock(user_text), *images]),支援
        多模態(provider 需支援 image input,如 Anthropic / OpenAI vision)。
        無 images 時行為跟原本一樣(content 為 str)。
        """
        if ctx is None:
            ctx = AgentContext(session_id=self.session_id, user_id=self.user_id)
        else:
            # 確保 ctx 用 conversation 的 session_id / user_id
            ctx.session_id = self.session_id
            ctx.user_id = self.user_id

        # 共用 replacement_state(query_loop 會用 ctx.replacement_state)
        if self.persistence_enabled:
            ctx.replacement_state = self.replacement_state

        # Phase 7:傳 sandbox backend 進 ctx(若有)
        if self.sandbox_backend is not None:
            ctx.sandbox_backend = self.sandbox_backend

        # Phase 12:傳 file_state_cache 進 ctx(lazy 建立,跨 turn 共用)
        if self.file_state_cache is None:
            from orion_sdk.services.file_state import FileStateCache
            self.file_state_cache = FileStateCache()
        ctx.file_state_cache = self.file_state_cache

        # 延遲 init storage(避免測試強制建檔案)
        store = await self._ensure_storage()
        injected_context: str | None = None

        # ─── Phase 8:SessionStart + UserPromptSubmit hook ─────────────────
        if self.hooks.count("SessionStart") > 0 and not self._session_started:
            from orion_sdk.hooks.events import SessionStartEvent
            await self.hooks.fire(
                SessionStartEvent(
                    cwd=str(ctx.cwd),
                    resumed=bool(self.state_messages),
                    session_id=str(self.session_id),
                    user_id=self.user_id,
                ),
            )
        self._session_started = True
        ups_abort_reason: str | None = None
        if self.hooks.count("UserPromptSubmit") > 0:
            from orion_sdk.hooks.events import UserPromptSubmitEvent
            ups_result = await self.hooks.fire_user_prompt_submit(
                UserPromptSubmitEvent(
                    prompt=user_text,
                    session_id=str(self.session_id),
                    user_id=self.user_id,
                ),
            )
            if ups_result.abort:
                ups_abort_reason = ups_result.abort_reason or "no reason"
            else:
                injected_context = ups_result.additional_context

        if ups_abort_reason is not None:
            yield LoopTerminated(
                transition=Terminal(
                    reason=f"user_prompt_submit_aborted: {ups_abort_reason}",
                ),
                total_turns=self.stats.turns,
                final_messages=list(self.state_messages),
            )
            return

        # user 訊息進 state + 寫 transcript
        # 有 image attachments → 包成 list[ContentBlock];否則維持原 str 行為。
        if images:
            from orion_model.types import TextBlock
            content_blocks: list[Any] = []
            if user_text:
                content_blocks.append(TextBlock(text=user_text))
            content_blocks.extend(images)
            user_msg = NormalizedMessage(role="user", content=content_blocks)
        else:
            user_msg = NormalizedMessage(role="user", content=user_text)
        self.state_messages.append(user_msg)
        if store is not None:
            await store.record_message(user_msg)

        # ─── Phase 4 + cache 優化:組裝 system prompt + per-turn 注入 ────────
        # system prompt = [static, session_stable](皆 cacheable)
        # per_turn_text(memory + git_status)注入最後一個 user message,
        # 避免 volatile 內容破壞 system → messages 的 cache prefix 連續性。
        effective_system_prompt: str | list[str]
        # query_loop 看到的 messages(可能含 per-turn 注入版的 user msg)。
        # **不 mutate self.state_messages** — 否則 memory/git_status 會被
        # 當成對話歷史持久化,replay 時整段送回前端,看起來像 user 自己打的。
        messages_for_loop: list[NormalizedMessage] = list(self.state_messages)
        augmented_user_msg: NormalizedMessage | None = None
        try:
            # 從 ctx.cwd 取「workspace cwd」— 但只有 include_workspace_context=True
            # 才把它當「user 工作目錄」傳下去。否則 cwd=None,assembler 跳過
            # cwd-derived sections(git_status / project instructions / env cwd 顯示)。
            workspace_cwd = ctx.cwd if self.include_workspace_context else None
            parts = await fetch_system_prompt_parts(
                cwd=workspace_cwd,
                user_id=self.user_id,
                conversation_messages=self.state_messages,
                provider=self.provider if self.memory_enabled else None,
                mcp_manager=self.mcp_manager,
                custom_instructions_user=self.custom_instructions_user,
                custom_instructions_conversation=(
                    self.custom_instructions_conversation
                ),
                output_style=self.output_style,
                include_workspace_context=self.include_workspace_context,
                include_env_info=self.include_env_info,
            )
            effective_system_prompt = build_system_prompt_list(parts)
            # caller-supplied static prefix(self.system_prompt)併進 list[0]
            # (static block) — 兩者都是 session-stable,共用同一個 cache
            # breakpoint。 不開新 element,避免超出 Anthropic 4-bp 上限
            # (system list 每段都會被 _build_system_param 加 cache_control)。
            if self.system_prompt:
                if isinstance(effective_system_prompt, list) and effective_system_prompt:
                    head = self.system_prompt + "\n\n" + effective_system_prompt[0]
                    effective_system_prompt = [head, *effective_system_prompt[1:]]
                else:
                    effective_system_prompt = (
                        self.system_prompt + "\n\n" + str(effective_system_prompt)
                    )

            # per-turn 注入:只在 messages_for_loop 末尾換成 rendered 版,
            # self.state_messages 維持 bare,避免 memory 被持久化
            if (
                parts.per_turn_text
                and messages_for_loop
                and messages_for_loop[-1].role == "user"
            ):
                from orion_sdk.prompt.assembler import (
                    inject_per_turn_into_user_message,
                )
                augmented_user_msg = inject_per_turn_into_user_message(
                    messages_for_loop[-1], parts.per_turn_text
                )
                messages_for_loop[-1] = augmented_user_msg
        except Exception:  # noqa: BLE001 — fallback 到純靜態 block
            from orion_sdk.prompt.static_sections import render_static_block
            effective_system_prompt = render_static_block()
            if self.system_prompt:
                effective_system_prompt = (
                    self.system_prompt + "\n\n" + effective_system_prompt
                )

        # Phase 8:UserPromptSubmit hook 注入的額外 context(append 到 system prompt)
        if injected_context:
            if isinstance(effective_system_prompt, str):
                effective_system_prompt = effective_system_prompt + "\n\n" + injected_context
            else:
                effective_system_prompt = list(effective_system_prompt) + [injected_context]

        # ─── Phase 5:把 McpManager 的工具併進這次 turn 的 tools ────────────
        effective_tools: list[Tool[Any]] = list(self.tools)
        if self.mcp_manager is not None:
            mcp_tools = getattr(self.mcp_manager, "tools", [])
            if isinstance(mcp_tools, list):
                effective_tools.extend(mcp_tools)

        params = QueryParams(
            provider=self.provider,
            system_prompt=effective_system_prompt,
            tools=effective_tools,
            can_use_tool=self.can_use_tool,
            hooks=self.hooks,
            initial_messages=messages_for_loop,
            max_turns=self.max_turns,
            max_tokens_per_turn=self.max_tokens_per_turn,
            reasoning_effort=self.reasoning_effort,
        )

        # Phase 9:把整 turn 包進 OTel trace_turn
        from orion_sdk.telemetry.instrumentation import trace_turn

        with trace_turn(str(self.session_id), self.user_id, turn_index=self.stats.turns):
            async for ev in query_loop(params, ctx):
                yield ev

                # 累積 stats
                if isinstance(ev, AssistantTurnComplete):
                    self.stats.input_tokens += ev.input_tokens
                    self.stats.output_tokens += ev.output_tokens
                    self.stats.cache_read_tokens += ev.cache_read_tokens
                    self.stats.cache_creation_tokens += ev.cache_creation_tokens
                    self.stats.reasoning_tokens += ev.reasoning_tokens
                    # last turn — 覆蓋
                    self.stats.last_input_tokens = ev.input_tokens
                    self.stats.last_output_tokens = ev.output_tokens
                    self.stats.last_cache_read_tokens = ev.cache_read_tokens
                    self.stats.last_cache_creation_tokens = ev.cache_creation_tokens
                    self.stats.last_reasoning_tokens = ev.reasoning_tokens
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
                    # 把 augmented user msg 還原成 bare,避免 memory/git_status
                    # 隨 final_messages 持久化(下次 replay 會送整段給前端)
                    final = list(ev.final_messages)
                    if augmented_user_msg is not None:
                        for i, m in enumerate(final):
                            if m is augmented_user_msg:
                                final[i] = user_msg
                                break
                    self.state_messages = final
                    if store is not None:
                        await store.record_transition(
                            reason=ev.transition.reason,
                            total_turns=ev.total_turns,
                        )

                    # ─── Phase 3:fire-and-forget 萃取新 memory(失敗不影響)───
                    # 用 background task 而不是 await — extract_memories 是 LLM
                    # call(數秒),若 await 會卡住 generator return,連帶 caller
                    # (e.g. WebSocket runner)持有的 turn_lock 多撐數秒,user
                    # 看到 TerminalEvent 後送下一句會被 reject。
                    if self.memory_enabled and self.auto_extract_memories:
                        task = asyncio.create_task(
                            self._extract_memories_safely(list(self.state_messages)),
                        )
                        self._pending_extract_tasks.add(task)
                        task.add_done_callback(self._pending_extract_tasks.discard)

    async def compact(self, *, force: bool = False) -> CompactResult:
        """壓縮 `self.state_messages` — 用 LLM 把前段對話摘要成單一 TombstoneBlock。

        force=True → 立刻壓(手動 /compact),跳過 threshold。
        force=False → 看 `self.auto_compact_threshold`(或 env / 預設)再決定。

        直接 mutate `self.state_messages`。回傳 CompactResult 含摘要文字 + token
        前後估算,呼叫方可推 event / 顯示 UI。
        """
        from orion_sdk.compact.auto import (
            compact_messages_now,
            estimate_token_count,
        )
        from orion_sdk.compact.auto import (
            auto_compact_if_needed,
        )

        original = self.state_messages
        original_count = len(original)
        if original_count < 2:
            return CompactResult(
                was_compacted=False,
                summary="",
                before_tokens=0,
                after_tokens=estimate_token_count(original),
                kept_message_count=original_count,
            )

        # 摘要 provider:有 override 用便宜 model;沒設用對話本身的 provider
        summary_provider = self.compact_summary_provider or self.provider
        if force:
            new_messages = await compact_messages_now(
                original,
                provider=summary_provider,
                locale=self.compact_summary_locale,
            )
            was_compacted = new_messages is not original and len(new_messages) < original_count
        else:
            # threshold 判斷用 chat provider 的 context window;摘要 LLM call 用 summary_provider
            new_messages, was_compacted = await auto_compact_if_needed(
                original,
                provider=self.provider,
                summary_provider=summary_provider,
                threshold=self.auto_compact_threshold,
                locale=self.compact_summary_locale,
            )

        if not was_compacted:
            return CompactResult(
                was_compacted=False,
                summary="",
                before_tokens=0,
                after_tokens=estimate_token_count(original),
                kept_message_count=original_count,
            )

        # 從新 messages 抽出 tombstone 的 summary / before tokens(就是替換進去那張)
        summary = ""
        before_tokens = 0
        # 替換規則:前段 [0..cutoff-1] → 單一 user role tombstone(index 0)
        first = new_messages[0] if new_messages else None
        if first is not None and isinstance(first.content, list):
            from orion_model.types import TombstoneBlock
            for b in first.content:
                if isinstance(b, TombstoneBlock):
                    summary = b.summary
                    before_tokens = b.original_token_count
                    break

        before_state = self.state_messages
        self.state_messages = new_messages
        # 更新 replacement_state — 整段前綴被 tombstone 替換,那些 tool_use_id
        # 也跟著失效,後續 turn 不該再 reference。直接重置 set / dict。
        self.replacement_state.seen_ids.clear()
        self.replacement_state.replacements.clear()
        _log.info(
            "conversation %s compacted: %d → %d messages (before_tokens=%d)",
            self.session_id,
            len(before_state),
            len(new_messages),
            before_tokens,
        )

        return CompactResult(
            was_compacted=True,
            summary=summary,
            before_tokens=before_tokens,
            after_tokens=estimate_token_count(new_messages),
            kept_message_count=len(new_messages),
        )

    async def _extract_memories_safely(
        self, messages: list[NormalizedMessage]
    ) -> None:
        try:
            from orion_sdk.memory.paths import MemoryPaths
            if self.memory_dir_override is not None:
                # override 是 .../memory 路徑;MemoryPaths.memory_dir = root/"memory"
                paths = MemoryPaths(
                    user_id=self.user_id,
                    root=self.memory_dir_override.parent,
                )
                # safety:若 dir name 不是 "memory" 就 fallback 給 user-level
                if paths.memory_dir != self.memory_dir_override:
                    paths = user_memory_paths(self.user_id)
            else:
                paths = user_memory_paths(self.user_id)
            existing = scan_memory_dir(paths).memories
            await extract_memories(
                messages, existing, provider=self.provider, paths=paths,
            )
        except Exception:  # noqa: BLE001
            pass

    async def _ensure_storage(self) -> SessionStorage | None:
        """Lazy 初始化 SessionStorage。"""
        if not self.persistence_enabled:
            return None
        if self._session_storage is None:
            # Phase 27:若有 db_engine,SessionStorage 會把 record_message dual-write
            # 進 messages 表(JSONL 仍是 events audit log)。
            from sqlalchemy.ext.asyncio import AsyncEngine

            engine = self.db_engine if isinstance(self.db_engine, AsyncEngine) else None
            store = SessionStorage.open(self.session_id, db_engine=engine)
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
        db_engine: Any = None,
    ) -> Conversation:
        """從既有 session 載入 transcript,重建 Conversation。

        Args:
            session_id: 之前 conversation 的 session_id
            provider / tools / system_prompt / ...: 同 __init__,system_prompt 若 None
                會試著從 transcript 的 session-meta record 取出。
            db_engine: Phase 31-H cross-machine resume — 若提供 AsyncEngine,
                從 DB 載入 state_messages(優先於檔案 transcript)。其他機器上
                resume 同一 session 時用。大 tool result 仍以 placeholder 形式存在
                (跨機器看不到 ~/.orion/sessions/.../tool-results/ 內容)。

        Returns:
            Conversation 實例,state_messages + replacement_state 已重建。
        """
        import sys

        from orion_sdk.storage.resume import fetch_db_messages, load_session

        prebaked_messages = None
        if db_engine is not None:
            prebaked_messages = await fetch_db_messages(session_id, db_engine)

        snapshot = load_session(session_id, prebaked_messages=prebaked_messages)
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
