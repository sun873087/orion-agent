"""B2 跨對話搜尋 tools — unit tests。

涵蓋:
- FTS5 schema 建好 + trigger sync(INSERT/UPDATE/DELETE)
- search_messages_fts 基本查詢 / session_filter / 空 query / 無結果
- list_recent_chats since/until 範圍 / limit
- ConversationSearchTool.call empty query / no results / success
- RecentChatsTool.call success
- Backfill migration:若 FTS5 row count 落後就 rebuild
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine

from orion_cowork_sidecar import storage
from orion_cowork_sidecar.search_tools import (
    ConversationSearchInput,
    ConversationSearchTool,
    RecentChatsInput,
    RecentChatsTool,
)
from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent
from orion_sdk.storage.db.engine import db_session
from orion_sdk.storage.db.models import ConversationMetadata as MetaRow
from orion_sdk.storage.db.models import Message as MessageRow
from orion_sdk.storage.db.models import Session as SessionRow


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    """Tmp cowork.db,每 test 獨立。init_storage() 順手建 FTS5 schema + triggers。"""
    with tempfile.TemporaryDirectory(prefix="cowork-search-") as d:
        os.environ["ORION_COWORK_DATA_DIR"] = d
        eng = await storage.init_storage()
        yield eng
        await eng.dispose()
        os.environ.pop("ORION_COWORK_DATA_DIR", None)


async def _insert_session(
    engine: AsyncEngine, sid: str, title: str | None = None,
) -> None:
    """用 SDK ORM 建 sessions row — default 自動填 NOT NULL 欄位
    (n_turns / n_messages / input_tokens / output_tokens / created_at / updated_at)。"""
    async with db_session(engine) as s:
        s.add(SessionRow(
            id=sid,
            user_id=storage.LOCAL_USER_ID,
            provider="anthropic",
            model="claude-sonnet-4-6",
        ))
        await s.commit()
    if title:
        async with db_session(engine) as s:
            s.add(MetaRow(session_id=sid, title=title))
            await s.commit()


async def _insert_message(
    engine: AsyncEngine,
    sid: str,
    role: str,
    raw_text: str,
    created_at_iso: str | None = None,
) -> str:
    """用 SDK ORM 寫 messages row,raw_text 填好讓 FTS5 trigger 抓到。"""
    from datetime import datetime
    msg_id = str(uuid.uuid4())
    async with db_session(engine) as s:
        kwargs: dict = dict(
            id=msg_id,
            session_id=sid,
            role=role,
            content_json=raw_text,
            raw_text=raw_text,
        )
        if created_at_iso:
            kwargs["created_at"] = datetime.fromisoformat(created_at_iso)
        s.add(MessageRow(**kwargs))
        await s.commit()
    return msg_id


# ─── Storage layer ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fts5_table_created(engine: AsyncEngine) -> None:
    """init_storage 應該建 messages_fts virtual table。"""
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='messages_fts'"
        )
        assert result.first() is not None


@pytest.mark.asyncio
async def test_fts5_triggers_sync_on_insert(engine: AsyncEngine) -> None:
    """INSERT message 後 trigger 自動 sync 進 FTS5 — 立刻搜得到。"""
    sid = str(uuid.uuid4())
    await _insert_session(engine, sid, title="OAuth 設定")
    await _insert_message(engine, sid, "user", "如何設定 OAuth 重定向 URL")
    results = await storage.search_messages_fts(engine, "OAuth", limit=10)
    assert len(results) == 1
    assert results[0]["session_id"] == sid
    assert results[0]["role"] == "user"
    assert "OAuth" in results[0]["snippet"]
    assert results[0]["session_title"] == "OAuth 設定"


@pytest.mark.asyncio
async def test_fts5_triggers_sync_on_delete(engine: AsyncEngine) -> None:
    """DELETE message 後 FTS5 也跟著清。"""
    sid = str(uuid.uuid4())
    await _insert_session(engine, sid)
    msg_id = await _insert_message(engine, sid, "user", "Python decorator 怎麼用")
    # 確認搜得到
    assert len(await storage.search_messages_fts(engine, "decorator")) == 1
    # Delete
    async with engine.connect() as conn:
        await conn.exec_driver_sql("DELETE FROM messages WHERE id = ?", (msg_id,))
        await conn.commit()
    # 搜不到
    assert len(await storage.search_messages_fts(engine, "decorator")) == 0


@pytest.mark.asyncio
async def test_fts5_triggers_sync_on_update(engine: AsyncEngine) -> None:
    """UPDATE raw_text → 舊內容搜不到,新內容搜得到。"""
    sid = str(uuid.uuid4())
    await _insert_session(engine, sid)
    msg_id = await _insert_message(engine, sid, "assistant", "use grep -r pattern")
    assert len(await storage.search_messages_fts(engine, "grep")) == 1
    # Update
    async with engine.connect() as conn:
        await conn.exec_driver_sql(
            "UPDATE messages SET raw_text = ? WHERE id = ?",
            ("use ripgrep instead", msg_id),
        )
        await conn.commit()
    assert len(await storage.search_messages_fts(engine, "grep")) == 0
    assert len(await storage.search_messages_fts(engine, "ripgrep")) == 1


@pytest.mark.asyncio
async def test_search_session_filter(engine: AsyncEngine) -> None:
    """session_filter 限定範圍,別的 session 搜不到。"""
    sid1, sid2 = str(uuid.uuid4()), str(uuid.uuid4())
    await _insert_session(engine, sid1)
    await _insert_session(engine, sid2)
    await _insert_message(engine, sid1, "user", "kubernetes deployment yaml")
    await _insert_message(engine, sid2, "user", "kubernetes ingress config")
    # 全範圍找 kubernetes — 兩條都有
    all_results = await storage.search_messages_fts(engine, "kubernetes", limit=10)
    assert len(all_results) == 2
    # 限 sid1 — 只一條
    filtered = await storage.search_messages_fts(
        engine, "kubernetes", limit=10, session_filter=sid1,
    )
    assert len(filtered) == 1
    assert filtered[0]["session_id"] == sid1


@pytest.mark.asyncio
async def test_search_empty_query(engine: AsyncEngine) -> None:
    """空 query 回空 list,不丟例外。"""
    sid = str(uuid.uuid4())
    await _insert_session(engine, sid)
    await _insert_message(engine, sid, "user", "anything")
    assert await storage.search_messages_fts(engine, "") == []
    assert await storage.search_messages_fts(engine, "   ") == []


@pytest.mark.asyncio
async def test_search_no_match(engine: AsyncEngine) -> None:
    """沒命中回空 list。"""
    sid = str(uuid.uuid4())
    await _insert_session(engine, sid)
    await _insert_message(engine, sid, "user", "rust async runtime")
    results = await storage.search_messages_fts(engine, "kubernetes")
    assert results == []


@pytest.mark.asyncio
async def test_search_skips_empty_raw_text(engine: AsyncEngine) -> None:
    """raw_text 為 NULL / 空字串的 row 不該進 FTS5(trigger guard)。"""
    sid = str(uuid.uuid4())
    await _insert_session(engine, sid)
    msg_id = str(uuid.uuid4())
    async with engine.connect() as conn:
        # raw_text=NULL 直接 INSERT — trigger 應該 skip
        await conn.exec_driver_sql(
            "INSERT INTO messages (id, session_id, role, content_json, raw_text, "
            "created_at) VALUES (?, ?, ?, ?, NULL, datetime('now'))",
            (msg_id, sid, "user", json.dumps([{"type": "image"}])),
        )
        await conn.commit()
        # FTS 應該沒這 row
        result = await conn.exec_driver_sql(
            "SELECT COUNT(*) FROM messages_fts WHERE message_id = ?", (msg_id,),
        )
        assert result.scalar() == 0


@pytest.mark.asyncio
async def test_list_recent_chats_orders_by_activity(engine: AsyncEngine) -> None:
    """最近活動倒序,last_user_msg 帶回。"""
    sid1, sid2 = str(uuid.uuid4()), str(uuid.uuid4())
    await _insert_session(engine, sid1, title="舊")
    await _insert_session(engine, sid2, title="新")
    await _insert_message(
        engine, sid1, "user", "舊問題", created_at_iso="2026-05-01T10:00:00",
    )
    await _insert_message(
        engine, sid2, "user", "新問題", created_at_iso="2026-05-23T10:00:00",
    )
    chats = await storage.list_recent_chats(engine, limit=10)
    assert len(chats) == 2
    # 最新在前
    assert chats[0]["session_id"] == sid2
    assert chats[0]["title"] == "新"
    assert chats[0]["last_user_msg"] == "新問題"
    assert chats[1]["session_id"] == sid1


@pytest.mark.asyncio
async def test_list_recent_chats_since_filter(engine: AsyncEngine) -> None:
    """since 限定時間下限。"""
    sid1, sid2 = str(uuid.uuid4()), str(uuid.uuid4())
    await _insert_session(engine, sid1)
    await _insert_session(engine, sid2)
    await _insert_message(
        engine, sid1, "user", "old", created_at_iso="2026-05-01T10:00:00",
    )
    await _insert_message(
        engine, sid2, "user", "recent", created_at_iso="2026-05-23T10:00:00",
    )
    chats = await storage.list_recent_chats(engine, since="2026-05-10")
    assert len(chats) == 1
    assert chats[0]["session_id"] == sid2


@pytest.mark.asyncio
async def test_backfill_when_fts_lags(engine: AsyncEngine) -> None:
    """模擬 FTS table 落後(直接 DELETE FTS)— init_storage 再跑會 backfill。"""
    sid = str(uuid.uuid4())
    await _insert_session(engine, sid)
    await _insert_message(engine, sid, "user", "git rebase interactive")
    await _insert_message(engine, sid, "assistant", "use --interactive flag")
    # 確認 trigger 已 sync
    async with engine.connect() as conn:
        c = await conn.exec_driver_sql("SELECT COUNT(*) FROM messages_fts")
        assert c.scalar() == 2
        # 模擬 FTS 落後:全清掉 + 跳過 trigger 重新 setup
        await conn.exec_driver_sql("DELETE FROM messages_fts")
        await conn.commit()
        c = await conn.exec_driver_sql("SELECT COUNT(*) FROM messages_fts")
        assert c.scalar() == 0
    # Re-run init 應該 backfill
    await storage._ensure_messages_fts(engine)
    async with engine.connect() as conn:
        c = await conn.exec_driver_sql("SELECT COUNT(*) FROM messages_fts")
        assert c.scalar() == 2
    # 可搜
    assert len(await storage.search_messages_fts(engine, "rebase")) == 1


# ─── Tool layer ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_conversation_search_tool_empty_query(engine: AsyncEngine) -> None:
    """ConversationSearchTool empty query 回 ErrorEvent。"""

    async def provider() -> AsyncEngine:
        return engine

    tool = ConversationSearchTool(provider)
    ctx = AgentContext()
    events = []
    async for ev in tool.call(ConversationSearchInput(query=""), ctx):
        events.append(ev)
    assert len(events) == 1
    assert isinstance(events[0], ErrorEvent)
    assert "empty" in events[0].message


@pytest.mark.asyncio
async def test_conversation_search_tool_no_results(engine: AsyncEngine) -> None:
    """沒命中回友善 TextEvent。"""

    async def provider() -> AsyncEngine:
        return engine

    tool = ConversationSearchTool(provider)
    ctx = AgentContext()
    events = []
    async for ev in tool.call(ConversationSearchInput(query="unicorn"), ctx):
        events.append(ev)
    assert len(events) == 1
    assert isinstance(events[0], TextEvent)
    assert "No messages found" in events[0].text


@pytest.mark.asyncio
async def test_conversation_search_tool_success(engine: AsyncEngine) -> None:
    """有結果回 JSON TextEvent。"""
    sid = str(uuid.uuid4())
    await _insert_session(engine, sid, title="OAuth")
    await _insert_message(engine, sid, "user", "OAuth 重定向 URL 怎麼設")

    async def provider() -> AsyncEngine:
        return engine

    tool = ConversationSearchTool(provider)
    ctx = AgentContext()
    events = []
    async for ev in tool.call(ConversationSearchInput(query="OAuth"), ctx):
        events.append(ev)
    assert len(events) == 1
    assert isinstance(events[0], TextEvent)
    payload = json.loads(events[0].text)
    assert payload["query"] == "OAuth"
    assert payload["count"] == 1
    assert payload["results"][0]["session_id"] == sid


@pytest.mark.asyncio
async def test_recent_chats_tool_success(engine: AsyncEngine) -> None:
    """RecentChatsTool 回 JSON TextEvent。"""
    sid = str(uuid.uuid4())
    await _insert_session(engine, sid, title="昨日聊天")
    await _insert_message(
        engine, sid, "user", "hi", created_at_iso="2026-05-23T10:00:00",
    )

    async def provider() -> AsyncEngine:
        return engine

    tool = RecentChatsTool(provider)
    ctx = AgentContext()
    events = []
    async for ev in tool.call(RecentChatsInput(), ctx):
        events.append(ev)
    assert len(events) == 1
    assert isinstance(events[0], TextEvent)
    payload = json.loads(events[0].text)
    assert payload["count"] == 1
    assert payload["chats"][0]["session_id"] == sid
    assert payload["chats"][0]["title"] == "昨日聊天"


@pytest.mark.asyncio
async def test_recent_chats_tool_empty(engine: AsyncEngine) -> None:
    """沒對話回友善 TextEvent。"""

    async def provider() -> AsyncEngine:
        return engine

    tool = RecentChatsTool(provider)
    ctx = AgentContext()
    events = []
    async for ev in tool.call(RecentChatsInput(), ctx):
        events.append(ev)
    assert len(events) == 1
    assert isinstance(events[0], TextEvent)
    assert "No recent chats" in events[0].text
