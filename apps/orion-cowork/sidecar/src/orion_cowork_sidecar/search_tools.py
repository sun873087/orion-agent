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
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncEngine

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput


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
    session_id: str | None = Field(
        None,
        description=(
            "Optional: restrict search to a single past conversation by its UUID. "
            "Leave empty to search across all conversations."
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
        "is relevant. Read-only, never modifies anything."
    )
    input_schema = ConversationSearchInput

    def __init__(self, engine_provider: Any) -> None:
        # engine_provider 是 callable() -> AsyncEngine — 避免在 build_tool_set
        # 時 engine 還沒 init。Cowork sidecar 把 self.ensure_engine 傳進來。
        self._engine_provider = engine_provider

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
        try:
            results = await storage.search_messages_fts(
                engine,
                query,
                limit=max(1, min(50, input.limit)),
                session_filter=input.session_id,
            )
        except Exception as e: # noqa: BLE001
            yield ErrorEvent(message=f"search failed: {type(e).__name__}: {e}")
            return
        if not results:
            yield TextEvent(text=f"No messages found matching {query!r}.")
            return
        # 給 LLM 結構化 JSON,自己決定怎麼用(quote snippet / open session 等)
        payload = {
            "query": query,
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


class RecentChatsTool:
    name = "RecentChats"
    description = (
        "List the user's recent conversations with you, ordered by most-recent "
        "activity. Use this when the user references time ('yesterday', 'last "
        "week', 'this morning') or asks 'what were we working on'. Returns "
        "session metadata (title, message count, last user message snippet, "
        "last activity timestamp). For full text search across past conversations "
        "use ConversationSearch instead. Read-only."
    )
    input_schema = RecentChatsInput

    def __init__(self, engine_provider: Any) -> None:
        self._engine_provider = engine_provider

    async def call(
        self,
        input: RecentChatsInput,
        ctx: AgentContext, # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        engine: AsyncEngine = await self._engine_provider()
        from orion_cowork_sidecar import storage
        try:
            chats = await storage.list_recent_chats(
                engine,
                since=input.since,
                until=input.until,
                limit=max(1, min(50, input.limit)),
            )
        except Exception as e: # noqa: BLE001
            yield ErrorEvent(message=f"recent chats query failed: {type(e).__name__}: {e}")
            return
        if not chats:
            yield TextEvent(text="No recent chats found in the given range.")
            return
        payload = {"count": len(chats), "chats": chats}
        yield TextEvent(text=json.dumps(payload, ensure_ascii=False, indent=2))

    def is_concurrency_safe(self, input: RecentChatsInput) -> bool: # noqa: ARG002
        return True

    def is_read_only(self, input: RecentChatsInput) -> bool: # noqa: ARG002
        return True

    def max_result_size_chars(self) -> int | float:
        # 50 chats × ~400 chars metadata = ~20KB
        return 25000
