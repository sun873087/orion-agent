"""Cowork 專屬 conversation search tools — 給 LLM「想起」之前對話用。

對齊 Anthropic 的 conversation_search / recent_chats tool 設計:
- 工具 description 引導 LLM 用「實質性關鍵字」(名詞 / 專有名詞 / 技術術語)
- 後端 SQLite FTS5 全文索引(SDK 已用 SQLite,FTS5 是內建 extension)
- 不走 vector embedding(對 cowork local 場景 keyword + BM25 ranker 性價比更高)

兩個 tool:
- `ConversationSearchTool`:keyword 搜跨 session message 內容,回 snippet 跟
  session reference,LLM 可拿來綜合回答「之前你說過 X」
- `RecentChatsTool`:時間範圍撈最近活動 session,LLM 可拿來「昨天我們聊了什麼」

兩個都是 read-only(不寫 DB),permission default 不擋。

Scope 設計:都支援 `scope` 參數 — `all`(預設,全 cowork.db)/ `project`
(僅當前 session 所屬 project 旗下 sessions)/ `collaboration`(僅當前 multi-pane
window 內所有 panes)/ `session`(僅當前 session)。LLM 無法自己取 project_id /
collaboration_id;sidecar 從當前 session 自動補(類似 schedule tool pattern)。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Literal

from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncEngine

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput


ScopeType = Literal["all", "project", "collaboration", "session"]


async def _resolve_scope_filters(
    engine: AsyncEngine,
    scope: str,
    current_session_id: str | None,
) -> tuple[str | None, str | None, str | None]:
    """把 scope 字串解成 (session_filter, project_filter, collaboration_filter)。

    LLM 沒法自己取 project_id / collaboration_id;sidecar 從當前 session
    auto-fill。當前 session 沒對應 project / collab 時對應 filter 維持 None
    (但 scope=project/collaboration 仍應 narrow — 用「不可能存在」哨兵
    `__NONE__`,讓 SQL 0 命中,避免誤回全部)。
    """
    if scope == "session":
        return (current_session_id or "__NONE__", None, None)
    if scope == "project":
        if not current_session_id:
            return (None, "__NONE__", None)
        from orion_cowork_sidecar import storage
        ext = await storage.get_session_ext(engine, current_session_id)
        return (None, ext.get("project_id") or "__NONE__", None)
    if scope == "collaboration":
        if not current_session_id:
            return (None, None, "__NONE__")
        from orion_cowork_sidecar import storage
        ext = await storage.get_session_ext(engine, current_session_id)
        return (None, None, ext.get("collaboration_id") or "__NONE__")
    # "all" 或未知值
    return (None, None, None)


# ─── ConversationSearchTool ────────────────────────────────────────────


class ConversationSearchInput(ToolInput):
    query: str = Field(
        ...,
        description=(
            "Substantive keywords to search for — nouns, proper names, technical "
            "terms (e.g. 'OAuth', 'kubernetes', 'invoice format'). Avoid verbs "
            "and stop words ('how to', 'about', 'do', 'is'). Multiple keywords "
            "are AND-combined. Wrap multi-word phrases in double quotes."
        ),
    )
    limit: int = Field(
        10,
        description="Max number of matching messages to return. 1-50, default 10.",
    )
    scope: ScopeType = Field(
        "all",
        description=(
            "Search scope. 'all' (default): every past conversation in the local "
            "DB. 'project': only conversations under the same project as the "
            "current session (the user is working in this project right now). "
            "'collaboration': only the panes in the current multi-pane "
            "collaboration window. 'session': only the current conversation. "
            "Use 'project' when the user says 'in this project' / 'we have done "
            "before in this codebase'. Use 'collaboration' when other panes' "
            "context matters ('what did @reviewer just say', 'did anyone else "
            "look at X'). If the current session has no project / collaboration "
            "binding the scope narrows to zero results — fall back to 'all'."
        ),
    )
    session_id: str | None = Field(
        None,
        description=(
            "Optional: restrict search to a single past conversation by its UUID. "
            "Overrides 'scope' when provided. Leave empty to use scope."
        ),
    )


class ConversationSearchTool:
    name = "ConversationSearch"
    description = (
        "Search across the user's past conversations with you for specific keywords. "
        "Use this when the user references something you might have discussed "
        "before ('like we talked about', 'remember the X thing', 'what was that "
        "command'), or when you want to recall prior context to answer better.\n\n"
        "Best results with substantive keywords (nouns / proper names / technical "
        "terms). Returns matching message snippets with session IDs and timestamps. "
        "Snippets are excerpts around the match — read them to decide if a session "
        "is relevant. Read-only, never modifies anything.\n\n"
        "Use `scope` to narrow: 'project' for 'in this project / codebase', "
        "'collaboration' for 'what did the other panes say', 'session' for "
        "within the current conversation, 'all' (default) for everything.\n\n"
        "NOTE: Messages the user explicitly marked with 👎 (negative feedback) "
        "are excluded from results — the user signaled they didn't want that "
        "answer to be referenced again. If you can't find something the user "
        "thinks you should remember, that may be why."
    )
    input_schema = ConversationSearchInput

    def __init__(
        self,
        engine_provider: Any,
        current_session_id: str | None = None,
    ) -> None:
        # engine_provider 是 callable() -> AsyncEngine — 避免在 build_tool_set
        # 時 engine 還沒 init。Cowork sidecar 把 self.ensure_engine 傳進來。
        # current_session_id 是 build 該 Conversation 當下的 session id(對齊
        # AskPaneTool / schedule callback pattern),scope=project/collaboration
        # 時用來 auto-fill 對應 id。
        self._engine_provider = engine_provider
        self._current_session_id = current_session_id

    async def call(
        self,
        input: ConversationSearchInput,
        ctx: AgentContext, # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        query = input.query.strip()
        if not query:
            yield ErrorEvent(message="query is empty")
            return
        engine: AsyncEngine = await self._engine_provider()
        from orion_cowork_sidecar import storage
        # session_id 顯式給 > scope 自動 resolve
        if input.session_id:
            sf, pf, cf = input.session_id, None, None
        else:
            sf, pf, cf = await _resolve_scope_filters(
                engine, input.scope, self._current_session_id,
            )
        try:
            results = await storage.search_messages_fts(
                engine,
                query,
                limit=max(1, min(50, input.limit)),
                session_filter=sf,
                project_filter=pf,
                collaboration_filter=cf,
            )
        except Exception as e: # noqa: BLE001
            yield ErrorEvent(message=f"search failed: {type(e).__name__}: {e}")
            return
        if not results:
            yield TextEvent(text=f"No messages found matching {query!r} (scope={input.scope}).")
            return
        # 給 LLM 結構化 JSON,自己決定怎麼用(quote snippet / open session 等)
        payload = {
            "query": query,
            "scope": input.scope,
            "count": len(results),
            "results": results,
        }
        yield TextEvent(text=json.dumps(payload, ensure_ascii=False, indent=2))

    def is_concurrency_safe(self, input: ConversationSearchInput) -> bool: # noqa: ARG002
        return True

    def is_read_only(self, input: ConversationSearchInput) -> bool: # noqa: ARG002
        return True

    def max_result_size_chars(self) -> int | float:
        # 50 results × ~300 chars snippet = ~15KB,留 buffer 20KB
        return 20000


# ─── RecentChatsTool ────────────────────────────────────────────────


class RecentChatsInput(ToolInput):
    since: str | None = Field(
        None,
        description=(
            "Optional ISO 8601 datetime — only return chats with activity since "
            "this point (e.g. '2026-05-01' or '2026-05-24T08:00:00')."
        ),
    )
    until: str | None = Field(
        None,
        description="Optional ISO 8601 datetime — upper bound on activity time.",
    )
    limit: int = Field(
        20,
        description="Max number of chats to return. 1-50, default 20.",
    )
    scope: ScopeType = Field(
        "all",
        description=(
            "Same semantics as ConversationSearch.scope. 'all' lists every "
            "recent chat in the local DB; 'project' only chats under the "
            "current session's project; 'collaboration' only panes in the "
            "current multi-pane window; 'session' degrades to the current "
            "session only (mostly useful as a debug shortcut)."
        ),
    )


class RecentChatsTool:
    name = "RecentChats"
    description = (
        "List the user's recent conversations with you, ordered by most-recent "
        "activity. Use this when the user references time ('yesterday', 'last "
        "week', 'this morning') or asks 'what were we working on'. Returns "
        "session metadata (title, message count, last user message snippet, "
        "last activity timestamp). For full text search across past conversations "
        "use ConversationSearch instead. Read-only.\n\n"
        "Use `scope` to narrow to the current project / collaboration when the "
        "user implies that context ('what have we done in this project today')."
    )
    input_schema = RecentChatsInput

    def __init__(
        self,
        engine_provider: Any,
        current_session_id: str | None = None,
    ) -> None:
        self._engine_provider = engine_provider
        self._current_session_id = current_session_id

    async def call(
        self,
        input: RecentChatsInput,
        ctx: AgentContext, # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        engine: AsyncEngine = await self._engine_provider()
        from orion_cowork_sidecar import storage
        sf, pf, cf = await _resolve_scope_filters(
            engine, input.scope, self._current_session_id,
        )
        # RecentChats 沒 session_filter param(列「最近 N 個 session」按 session
        # 過濾意義不大),scope=session 退化為一個 session;直接用 search 風格
        # 不另開 path。
        if sf and not (pf or cf):
            # scope=session — 直接回該 session info
            try:
                chats_all = await storage.list_recent_chats(
                    engine,
                    since=input.since,
                    until=input.until,
                    limit=max(1, min(50, input.limit)),
                )
            except Exception as e: # noqa: BLE001
                yield ErrorEvent(message=f"recent chats query failed: {type(e).__name__}: {e}")
                return
            chats = [c for c in chats_all if c.get("session_id") == sf]
        else:
            try:
                chats = await storage.list_recent_chats(
                    engine,
                    since=input.since,
                    until=input.until,
                    limit=max(1, min(50, input.limit)),
                    project_filter=pf,
                    collaboration_filter=cf,
                )
            except Exception as e: # noqa: BLE001
                yield ErrorEvent(message=f"recent chats query failed: {type(e).__name__}: {e}")
                return
        if not chats:
            yield TextEvent(text=f"No recent chats found in the given range (scope={input.scope}).")
            return
        payload = {"scope": input.scope, "count": len(chats), "chats": chats}
        yield TextEvent(text=json.dumps(payload, ensure_ascii=False, indent=2))

    def is_concurrency_safe(self, input: RecentChatsInput) -> bool: # noqa: ARG002
        return True

    def is_read_only(self, input: RecentChatsInput) -> bool: # noqa: ARG002
        return True

    def max_result_size_chars(self) -> int | float:
        # 50 chats × ~400 chars metadata = ~20KB
        return 25000
