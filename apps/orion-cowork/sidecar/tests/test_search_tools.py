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
async def test_set_and_get_feedback(engine: AsyncEngine) -> None:
    """Feedback CRUD:set positive / set negative / unset(None)。"""
    sid = str(uuid.uuid4())
    await _insert_session(engine, sid)
    mid1 = await _insert_message(engine, sid, "assistant", "hello")
    mid2 = await _insert_message(engine, sid, "assistant", "world")

    # Initially empty
    assert await storage.get_session_feedback_map(engine, sid) == {}

    # Set positive on mid1
    await storage.set_message_feedback(engine, mid1, "positive")
    fbmap = await storage.get_session_feedback_map(engine, sid)
    assert fbmap == {mid1: "positive"}

    # Set negative on mid2, update mid1 also to negative
    await storage.set_message_feedback(engine, mid2, "negative")
    await storage.set_message_feedback(engine, mid1, "negative")
    fbmap = await storage.get_session_feedback_map(engine, sid)
    assert fbmap == {mid1: "negative", mid2: "negative"}

    # Unset mid1 (feedback=None)
    await storage.set_message_feedback(engine, mid1, None)
    fbmap = await storage.get_session_feedback_map(engine, sid)
    assert fbmap == {mid2: "negative"}


@pytest.mark.asyncio
async def test_feedback_invalid_value_raises(engine: AsyncEngine) -> None:
    """非 'positive'/'negative' 應該 raise ValueError。"""
    sid = str(uuid.uuid4())
    await _insert_session(engine, sid)
    mid = await _insert_message(engine, sid, "assistant", "x")
    with pytest.raises(ValueError):
        await storage.set_message_feedback(engine, mid, "thumbs-up")


@pytest.mark.asyncio
async def test_search_excludes_negative_feedback(engine: AsyncEngine) -> None:
    """ConversationSearch 過濾掉 user 標 negative 的 message。"""
    sid = str(uuid.uuid4())
    await _insert_session(engine, sid)
    mid_good = await _insert_message(engine, sid, "assistant", "good Python answer")
    mid_bad = await _insert_message(engine, sid, "assistant", "bad Python answer")
    # Both indexed first
    all_results = await storage.search_messages_fts(engine, "Python", limit=10)
    assert len(all_results) == 2
    # Mark bad as negative → should be excluded
    await storage.set_message_feedback(engine, mid_bad, "negative")
    filtered = await storage.search_messages_fts(engine, "Python", limit=10)
    assert len(filtered) == 1
    assert filtered[0]["message_id"] == mid_good
    # Positive doesn't exclude
    await storage.set_message_feedback(engine, mid_good, "positive")
    still_filtered = await storage.search_messages_fts(engine, "Python", limit=10)
    assert len(still_filtered) == 1
    assert still_filtered[0]["message_id"] == mid_good


@pytest.mark.asyncio
async def test_feedback_cascade_on_message_delete(engine: AsyncEngine) -> None:
    """Message 被刪除時 feedback row 跟著清掉(FK ON DELETE CASCADE)。"""
    sid = str(uuid.uuid4())
    await _insert_session(engine, sid)
    mid = await _insert_message(engine, sid, "assistant", "x")
    await storage.set_message_feedback(engine, mid, "negative")
    assert await storage.get_session_feedback_map(engine, sid) == {mid: "negative"}
    # Delete the message
    async with engine.connect() as conn:
        # SQLite FK 預設 OFF;cowork.db SDK 是否打開 PRAGMA?保險用 explicit。
        await conn.exec_driver_sql("PRAGMA foreign_keys = ON")
        await conn.exec_driver_sql("DELETE FROM messages WHERE id = ?", (mid,))
        await conn.commit()
    assert await storage.get_session_feedback_map(engine, sid) == {}


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


# ─── Scope filter(project / collaboration / session) ─────────────────


@pytest.mark.asyncio
async def test_search_project_filter(engine: AsyncEngine) -> None:
    """storage layer:project_filter 只搜該 project 旗下 sessions。"""
    sid_a1, sid_a2, sid_b = (str(uuid.uuid4()) for _ in range(3))
    for sid in (sid_a1, sid_a2, sid_b):
        await _insert_session(engine, sid)
    # 三個 session 都有 OAuth message
    await _insert_message(engine, sid_a1, "user", "OAuth in project A session 1")
    await _insert_message(engine, sid_a2, "user", "OAuth in project A session 2")
    await _insert_message(engine, sid_b, "user", "OAuth in project B")
    # sid_a1 / sid_a2 → project P_A;sid_b → project P_B
    await storage.set_session_project(engine, sid_a1, "P_A")
    await storage.set_session_project(engine, sid_a2, "P_A")
    await storage.set_session_project(engine, sid_b, "P_B")
    # No filter → 3 結果
    all_r = await storage.search_messages_fts(engine, "OAuth", limit=10)
    assert len(all_r) == 3
    # project_filter=P_A → 2 結果
    pa = await storage.search_messages_fts(
        engine, "OAuth", limit=10, project_filter="P_A",
    )
    assert len(pa) == 2
    assert {r["session_id"] for r in pa} == {sid_a1, sid_a2}
    # project_filter=P_B → 1 結果
    pb = await storage.search_messages_fts(
        engine, "OAuth", limit=10, project_filter="P_B",
    )
    assert len(pb) == 1
    assert pb[0]["session_id"] == sid_b


@pytest.mark.asyncio
async def test_search_collaboration_filter(engine: AsyncEngine) -> None:
    """storage layer:collaboration_filter 只搜該 collab 旗下 panes。"""
    sid_x1, sid_x2, sid_solo = (str(uuid.uuid4()) for _ in range(3))
    for sid in (sid_x1, sid_x2, sid_solo):
        await _insert_session(engine, sid)
    await _insert_message(engine, sid_x1, "user", "kubernetes pane 1")
    await _insert_message(engine, sid_x2, "user", "kubernetes pane 2")
    await _insert_message(engine, sid_solo, "user", "kubernetes solo")
    coll = await storage.create_collaboration(engine, name="multi-pane test")
    await storage.add_pane_to_collaboration(
        engine, collaboration_id=coll.id, session_id=sid_x1, pane_name="@a",
    )
    await storage.add_pane_to_collaboration(
        engine, collaboration_id=coll.id, session_id=sid_x2, pane_name="@b",
    )
    # 全範圍 → 3
    assert len(await storage.search_messages_fts(engine, "kubernetes")) == 3
    # collab filter → 2
    in_coll = await storage.search_messages_fts(
        engine, "kubernetes", limit=10, collaboration_filter=coll.id,
    )
    assert len(in_coll) == 2
    assert {r["session_id"] for r in in_coll} == {sid_x1, sid_x2}


@pytest.mark.asyncio
async def test_tool_scope_project_auto_fills_from_current_session(
    engine: AsyncEngine,
) -> None:
    """Tool scope='project' 自動從 current_session_id 撈 project_id。"""
    sid_curr, sid_same_proj, sid_other_proj = (str(uuid.uuid4()) for _ in range(3))
    for sid in (sid_curr, sid_same_proj, sid_other_proj):
        await _insert_session(engine, sid)
    await _insert_message(engine, sid_curr, "user", "alpha keyword in curr")
    await _insert_message(engine, sid_same_proj, "user", "alpha keyword in same project")
    await _insert_message(engine, sid_other_proj, "user", "alpha keyword in other")
    await storage.set_session_project(engine, sid_curr, "PROJ1")
    await storage.set_session_project(engine, sid_same_proj, "PROJ1")
    await storage.set_session_project(engine, sid_other_proj, "PROJ2")

    async def provider() -> AsyncEngine:
        return engine

    tool = ConversationSearchTool(provider, current_session_id=sid_curr)
    ctx = AgentContext()
    events = []
    async for ev in tool.call(
        ConversationSearchInput(query="alpha", scope="project"), ctx,
    ):
        events.append(ev)
    assert len(events) == 1
    assert isinstance(events[0], TextEvent)
    payload = json.loads(events[0].text)
    assert payload["scope"] == "project"
    assert payload["count"] == 2
    sids = {r["session_id"] for r in payload["results"]}
    assert sids == {sid_curr, sid_same_proj}


@pytest.mark.asyncio
async def test_tool_scope_collaboration_no_collab_zero_results(
    engine: AsyncEngine,
) -> None:
    """Tool scope='collaboration' 但 current session 沒綁 collab → 0 結果
    (用 __NONE__ 哨兵防誤回全部)。"""
    sid_curr, sid_other = str(uuid.uuid4()), str(uuid.uuid4())
    await _insert_session(engine, sid_curr)
    await _insert_session(engine, sid_other)
    await _insert_message(engine, sid_curr, "user", "beta keyword")
    await _insert_message(engine, sid_other, "user", "beta keyword too")

    async def provider() -> AsyncEngine:
        return engine

    tool = ConversationSearchTool(provider, current_session_id=sid_curr)
    ctx = AgentContext()
    events = []
    async for ev in tool.call(
        ConversationSearchInput(query="beta", scope="collaboration"), ctx,
    ):
        events.append(ev)
    assert len(events) == 1
    assert isinstance(events[0], TextEvent)
    assert "No messages found" in events[0].text


@pytest.mark.asyncio
async def test_tool_scope_session_uses_current(engine: AsyncEngine) -> None:
    """Tool scope='session' 自動限定 current_session_id。"""
    sid_curr, sid_other = str(uuid.uuid4()), str(uuid.uuid4())
    await _insert_session(engine, sid_curr)
    await _insert_session(engine, sid_other)
    await _insert_message(engine, sid_curr, "user", "gamma here")
    await _insert_message(engine, sid_other, "user", "gamma there")

    async def provider() -> AsyncEngine:
        return engine

    tool = ConversationSearchTool(provider, current_session_id=sid_curr)
    ctx = AgentContext()
    events = []
    async for ev in tool.call(
        ConversationSearchInput(query="gamma", scope="session"), ctx,
    ):
        events.append(ev)
    payload = json.loads(events[0].text)
    assert payload["count"] == 1
    assert payload["results"][0]["session_id"] == sid_curr


@pytest.mark.asyncio
async def test_tool_explicit_session_id_overrides_scope(engine: AsyncEngine) -> None:
    """LLM 顯式給 session_id 時忽略 scope,優先 session_id。"""
    sid_curr, sid_target = str(uuid.uuid4()), str(uuid.uuid4())
    await _insert_session(engine, sid_curr)
    await _insert_session(engine, sid_target)
    await _insert_message(engine, sid_curr, "user", "delta in curr")
    await _insert_message(engine, sid_target, "user", "delta in target")

    async def provider() -> AsyncEngine:
        return engine

    tool = ConversationSearchTool(provider, current_session_id=sid_curr)
    ctx = AgentContext()
    events = []
    # scope=session 本來會限 sid_curr,但顯式 session_id=sid_target 覆蓋
    async for ev in tool.call(
        ConversationSearchInput(
            query="delta", scope="session", session_id=sid_target,
        ),
        ctx,
    ):
        events.append(ev)
    payload = json.loads(events[0].text)
    assert payload["count"] == 1
    assert payload["results"][0]["session_id"] == sid_target


@pytest.mark.asyncio
async def test_recent_chats_scope_project_filter(engine: AsyncEngine) -> None:
    """RecentChatsTool scope='project' 只列同 project 旗下 sessions。"""
    sid_curr, sid_same_proj, sid_other = (str(uuid.uuid4()) for _ in range(3))
    for sid in (sid_curr, sid_same_proj, sid_other):
        await _insert_session(engine, sid)
    await _insert_message(
        engine, sid_curr, "user", "x", created_at_iso="2026-05-20T10:00:00",
    )
    await _insert_message(
        engine, sid_same_proj, "user", "y", created_at_iso="2026-05-21T10:00:00",
    )
    await _insert_message(
        engine, sid_other, "user", "z", created_at_iso="2026-05-22T10:00:00",
    )
    await storage.set_session_project(engine, sid_curr, "PA")
    await storage.set_session_project(engine, sid_same_proj, "PA")
    await storage.set_session_project(engine, sid_other, "PB")

    async def provider() -> AsyncEngine:
        return engine

    tool = RecentChatsTool(provider, current_session_id=sid_curr)
    ctx = AgentContext()
    events = []
    async for ev in tool.call(RecentChatsInput(scope="project"), ctx):
        events.append(ev)
    payload = json.loads(events[0].text)
    assert payload["scope"] == "project"
    assert payload["count"] == 2
    assert {c["session_id"] for c in payload["chats"]} == {sid_curr, sid_same_proj}
