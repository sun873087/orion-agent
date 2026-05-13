"""Phase 28:介面刪 session 必須清光所有相關資料(fs + DB cascade)。

涵蓋:
- DbSessionManager.delete 同時清 DB sessions row + fs 目錄
- SQLite FK PRAGMA on → messages 跟著 CASCADE 刪
- conversation_metadata 也跟著 CASCADE 刪
- in-memory SessionManager.delete 也清 fs
- sweep_orphan_fs_sessions 清掉 DB 沒有的 fs 殘留
- sweep 安全閘:DB 空(沒 user)時 no-op,不誤砸資料
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from orion_agent.api.auth import dev_user_id
from orion_agent.api.session_manager import SessionManager
from orion_agent.api.session_manager_db import DbSessionManager
from orion_agent.core.conversation import Conversation
from orion_agent.llm.types import NormalizedMessage
from orion_agent.storage.db.engine import create_db_engine, db_session, init_db
from orion_agent.storage.db.models import (
    ConversationMetadata,
    Message as MessageRow,
    Session as SessionRow,
    User,
)
from orion_agent.storage.paths import session_paths
from orion_agent.storage.session import SessionStorage


class _DummyProvider:
    name = "anthropic"
    model = "claude-sonnet-4-6"

    async def stream(self, *args, **kwargs):  # noqa: ARG002, ANN001, ANN201
        raise NotImplementedError


def _dummy_conv() -> Conversation:
    return Conversation(provider=_DummyProvider())  # type: ignore[arg-type]


async def _new_user(engine, username: str) -> str:
    async with db_session(engine) as db:
        u = User(username=username, password_hash="x")
        db.add(u)
        await db.commit()
        await db.refresh(u)
    return u.id


@pytest.mark.anyio
async def test_db_delete_cascades_messages_and_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sessions row 刪 → messages + conversation_metadata 自動跟著刪。

    需 SQLite PRAGMA foreign_keys=ON 才會 enforce(本 phase 已加 listener)。
    """
    monkeypatch.setenv("ORION_SESSIONS_DIR", str(tmp_path))
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    uid = await _new_user(engine, "alice")
    mgr = DbSessionManager(engine=engine)

    sid = await mgr.create(user_id=uid, conversation=_dummy_conv())
    # 灌幾筆 messages + 一筆 metadata
    store = SessionStorage.open(sid, db_engine=engine)
    await store.record_meta(provider="anthropic", model="claude-sonnet-4-6")
    await store.record_message(NormalizedMessage(role="user", content="hi"))
    async with db_session(engine) as db:
        db.add(ConversationMetadata(session_id=str(sid), title="t", custom_instructions="x"))
        await db.commit()

    # delete session
    deleted = await mgr.delete(uid, sid)
    assert deleted is True

    # DB 應該全清
    async with db_session(engine) as db:
        sessions = list((await db.execute(select(SessionRow))).scalars())
        messages = list((await db.execute(select(MessageRow))).scalars())
        meta = list((await db.execute(select(ConversationMetadata))).scalars())
    assert sessions == []
    assert messages == [], f"messages should CASCADE, got {messages}"
    assert meta == [], f"conversation_metadata should CASCADE, got {meta}"
    await engine.dispose()


@pytest.mark.anyio
async def test_db_delete_removes_fs_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORION_SESSIONS_DIR", str(tmp_path))
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    uid = await _new_user(engine, "alice")
    mgr = DbSessionManager(engine=engine)
    sid = await mgr.create(user_id=uid, conversation=_dummy_conv())

    store = SessionStorage.open(sid, db_engine=engine)
    await store.record_meta(provider="anthropic", model="claude-sonnet-4-6")
    await store.record_message(NormalizedMessage(role="user", content="hi"))
    session_dir = session_paths(sid).root
    assert session_dir.exists()
    assert session_paths(sid).transcript.exists()

    await mgr.delete(uid, sid)
    assert not session_dir.exists(), "session dir should be removed on delete"
    await engine.dispose()


@pytest.mark.anyio
async def test_in_memory_delete_removes_fs_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """in-memory SessionManager 也要清 fs(CLI / no-DB 模式同樣有 transcript)。"""
    monkeypatch.setenv("ORION_SESSIONS_DIR", str(tmp_path))
    sid = uuid4()
    # 模擬:寫進 fs
    store = SessionStorage.open(sid)
    await store.record_meta(provider="anthropic", model="claude-sonnet-4-6")
    await store.record_message(NormalizedMessage(role="user", content="hi"))
    assert session_paths(sid).transcript.exists()

    sm = SessionManager()
    # 沒先 create 也應該清 fs(覆蓋使用者 cancel 後想清乾淨的情境)
    await sm.delete(dev_user_id("alice"), sid)
    assert not session_paths(sid).root.exists()


@pytest.mark.anyio
async def test_orphan_sweep_removes_dir_without_db_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORION_SESSIONS_DIR", str(tmp_path))
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    uid = await _new_user(engine, "alice")
    mgr = DbSessionManager(engine=engine)

    # 一個 valid session(有 DB row + fs)
    valid_sid = await mgr.create(user_id=uid, conversation=_dummy_conv())
    store = SessionStorage.open(valid_sid)
    await store.record_meta(provider="anthropic", model="claude-sonnet-4-6")

    # 一個 orphan(只有 fs,沒 DB row)
    orphan_sid = uuid4()
    orphan_store = SessionStorage.open(orphan_sid)
    await orphan_store.record_meta(provider="anthropic", model="claude-sonnet-4-6")

    removed = await mgr.sweep_orphan_fs_sessions()
    assert removed == 1
    assert session_paths(valid_sid).root.exists(), "valid session should be kept"
    assert not session_paths(orphan_sid).root.exists(), "orphan should be removed"
    await engine.dispose()


@pytest.mark.anyio
async def test_orphan_sweep_safety_gate_when_users_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DB users 表全空 → sweep no-op,不誤砸資料(防 DB init 失敗變大屠殺)。"""
    monkeypatch.setenv("ORION_SESSIONS_DIR", str(tmp_path))
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    mgr = DbSessionManager(engine=engine)

    # fs 上有 session 但 DB users 空
    sid = uuid4()
    store = SessionStorage.open(sid)
    await store.record_meta(provider="anthropic", model="claude-sonnet-4-6")

    removed = await mgr.sweep_orphan_fs_sessions()
    assert removed == 0
    assert session_paths(sid).root.exists(), "must not delete when DB looks unhealthy"
    await engine.dispose()


@pytest.mark.anyio
async def test_orphan_sweep_ignores_non_uuid_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """非 UUID 形式的目錄(user 手動建的)不刪。"""
    monkeypatch.setenv("ORION_SESSIONS_DIR", str(tmp_path))
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    await _new_user(engine, "alice")
    mgr = DbSessionManager(engine=engine)

    weird = tmp_path / "my-backup-stuff"
    weird.mkdir()
    (weird / "important.txt").write_text("don't delete me")

    removed = await mgr.sweep_orphan_fs_sessions()
    assert removed == 0
    assert weird.exists()
    await engine.dispose()
