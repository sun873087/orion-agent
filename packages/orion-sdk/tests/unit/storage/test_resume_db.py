"""H cross-machine resume — Conversation.resume(db_engine=...)。

驗證 db_engine 路徑會繞過檔案 transcript,直接從 DB 重建 state_messages。
模擬「機器 A 跑對話 → DB 同步 → 機器 B 沒有 ~/.orion/sessions/<id>/
transcript.jsonl 也能 resume」的情境。
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from orion_model.types import NormalizedMessage, TextBlock
from orion_sdk.storage.db.engine import create_db_engine, db_session, init_db
from orion_sdk.storage.db.models import Message as MessageRow
from orion_sdk.storage.db.models import Session as SessionRow
from orion_sdk.storage.db.models import User as UserRow
from orion_sdk.storage.resume import fetch_db_messages


@pytest.fixture
async def db_with_session():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    sid = uuid4()
    async with db_session(engine) as db:
        user = UserRow(id="u-cross", username="cross-user", password_hash="x")
        db.add(user)
        await db.flush()
        sess = SessionRow(id=str(sid), user_id=user.id, provider="anthropic", model="m")
        db.add(sess)
        await db.flush()
        # 兩個訊息:user prompt + assistant reply
        db.add(MessageRow(
            session_id=str(sid),
            role="user",
            content_json="hello from machine A",
        ))
        db.add(MessageRow(
            session_id=str(sid),
            role="assistant",
            content_json=[{"type": "text", "text": "I see machine A"}],
        ))
        await db.commit()
    yield engine, sid
    await engine.dispose()


async def test_fetch_db_messages_returns_persisted_messages(db_with_session) -> None:
    """H 基礎:DB 內 message rows 能透過 fetch_db_messages 還原。"""
    engine, sid = db_with_session
    messages = await fetch_db_messages(sid, engine)
    assert messages is not None
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content == "hello from machine A"
    assert messages[1].role == "assistant"
    assert isinstance(messages[1].content, list)
    assert isinstance(messages[1].content[0], TextBlock)
    assert messages[1].content[0].text == "I see machine A"


async def test_fetch_db_messages_returns_none_for_unknown_session(db_with_session) -> None:
    engine, _ = db_with_session
    missing = uuid4()
    messages = await fetch_db_messages(missing, engine)
    assert messages is None


async def test_resume_with_db_engine_bypasses_filesystem(
    db_with_session, monkeypatch
) -> None:
    """Conversation.resume(db_engine=engine) 從 DB 載 messages,
    不依賴 ~/.orion/sessions/<id>/transcript.jsonl(模擬 cross-machine)。"""
    from orion_sdk.core.conversation import Conversation
    from orion_sdk._testing import MockProvider

    engine, sid = db_with_session
    # 設環境讓 sessions dir 指到完全不存在的位置 → 檔案路徑會空
    monkeypatch.setenv("ORION_SESSIONS_DIR", "/nonexistent/cross-machine-test")

    conv = await Conversation.resume(
        sid,
        provider=MockProvider(),
        tools=[],
        db_engine=engine,
    )
    assert conv.session_id == sid
    assert len(conv.state_messages) == 2
    assert conv.state_messages[0].content == "hello from machine A"


async def test_resume_without_db_engine_uses_filesystem(monkeypatch) -> None:
    """確認舊行為(無 db_engine)仍走檔案路徑。"""
    from orion_sdk.core.conversation import Conversation
    from orion_sdk._testing import MockProvider
    from orion_sdk.storage.session import SessionStorage

    sid = uuid4()
    store = SessionStorage.open(sid)
    await store.record_meta(provider="anthropic", model="m", system_prompt="sp")
    await store.record_message(NormalizedMessage(role="user", content="from filesystem"))
    await store.record_transition(reason="natural_stop", total_turns=1)

    conv = await Conversation.resume(sid, provider=MockProvider(), tools=[])
    assert conv.session_id == sid
    assert any(m.content == "from filesystem" for m in conv.state_messages)
