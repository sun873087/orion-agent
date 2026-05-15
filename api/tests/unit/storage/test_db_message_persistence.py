"""Phase 27:SessionStorage dual-write 進 messages 表;load_session 從 DB resume。

- record_message + engine → messages 表 INSERT 一筆
- 多筆訊息保持插入順序(created_at + id 排序)
- load_session(sid, engine) DB 有 row → 從 DB 重建
- load_session(sid, engine) DB 空 → fallback JSONL
- load_session(sid, None) → JSONL only(legacy 路徑)
- DB INSERT 失敗(FK violation:session 不存在)→ warning,JSONL 仍寫入
- transitions / replacements 永遠走 JSONL(本 phase 沒搬 DB)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select

from orion_model.types import NormalizedMessage, TextBlock, ToolUseBlock
from orion_agent.storage.db.engine import create_db_engine, db_session, init_db
from orion_agent.storage.db.models import Message as MessageRow
from orion_agent.storage.db.models import Session as SessionRow
from orion_agent.storage.db.models import User
from orion_agent.storage.replacement_state import ReplacementDecision
from orion_agent.storage.resume import fetch_db_messages, load_session
from orion_agent.storage.session import SessionStorage


async def _seed_session_row(engine: Any, sid: str, user_id: str) -> None:
    """Phase 27:messages.session_id 是 FK to sessions.id,要先建 session row。"""
    async with db_session(engine) as db:
        u = User(id=user_id, username=f"u{user_id[:6]}", password_hash="x")
        db.add(u)
        await db.commit()
    async with db_session(engine) as db:
        row = SessionRow(
            id=sid,
            user_id=user_id,
            provider="anthropic",
            model="claude-sonnet-4-6",
            n_turns=0,
            n_messages=0,
        )
        db.add(row)
        await db.commit()


@pytest.mark.anyio
async def test_record_message_inserts_into_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORION_SESSIONS_DIR", str(tmp_path))
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    sid = uuid4()
    await _seed_session_row(engine, str(sid), str(uuid4()))

    store = SessionStorage.open(sid, db_engine=engine)
    await store.record_meta(provider="anthropic", model="claude-sonnet-4-6")
    await store.record_message(NormalizedMessage(role="user", content="hello"))
    await store.record_message(NormalizedMessage(role="assistant", content="hi back"))

    async with db_session(engine) as db:
        rows = list(
            (await db.execute(select(MessageRow).where(MessageRow.session_id == str(sid)))).scalars()
        )
    assert len(rows) == 2
    roles = [r.role for r in rows]
    assert "user" in roles and "assistant" in roles
    contents = [r.content_json for r in rows]
    assert "hello" in contents
    assert "hi back" in contents
    await engine.dispose()


@pytest.mark.anyio
async def test_jsonl_still_written_when_engine_provided(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """JSONL 仍是 audit log(transitions / replacements 需要),不能因有 DB 就停寫。"""
    monkeypatch.setenv("ORION_SESSIONS_DIR", str(tmp_path))
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    sid = uuid4()
    await _seed_session_row(engine, str(sid), str(uuid4()))

    store = SessionStorage.open(sid, db_engine=engine)
    await store.record_meta(provider="anthropic", model="claude-sonnet-4-6")
    await store.record_message(NormalizedMessage(role="user", content="hi"))
    await store.record_transition(reason="natural_stop", total_turns=1)

    transcript = tmp_path / str(sid) / "transcript.jsonl"
    assert transcript.exists()
    lines = transcript.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 3  # meta + message + transition
    await engine.dispose()


@pytest.mark.anyio
async def test_load_session_reads_db_when_messages_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """有 DB rows → resume 走 DB,不靠 JSONL。"""
    monkeypatch.setenv("ORION_SESSIONS_DIR", str(tmp_path))
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    sid = uuid4()
    await _seed_session_row(engine, str(sid), str(uuid4()))

    store = SessionStorage.open(sid, db_engine=engine)
    await store.record_meta(provider="anthropic", model="claude-sonnet-4-6")
    await store.record_message(NormalizedMessage(role="user", content="first"))
    await store.record_message(NormalizedMessage(role="assistant", content="second"))

    db_messages = await fetch_db_messages(sid, engine)
    assert db_messages is not None
    snapshot = load_session(sid, prebaked_messages=db_messages)
    assert len(snapshot.messages) == 2
    assert snapshot.messages[0].role == "user"
    assert snapshot.messages[0].content == "first"
    assert snapshot.messages[1].role == "assistant"
    assert snapshot.messages[1].content == "second"
    await engine.dispose()


@pytest.mark.anyio
async def test_load_session_falls_back_to_jsonl_when_db_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DB 空 → 用 JSONL(legacy session 補救路徑)。"""
    monkeypatch.setenv("ORION_SESSIONS_DIR", str(tmp_path))
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    sid = uuid4()
    # 故意不 seed session row + 不寫 DB:用 SessionStorage(無 engine)寫 JSONL
    store = SessionStorage.open(sid)
    await store.record_meta(provider="anthropic", model="claude-sonnet-4-6")
    await store.record_message(NormalizedMessage(role="user", content="legacy msg"))

    db_messages = await fetch_db_messages(sid, engine)
    assert db_messages is None  # DB 空
    snapshot = load_session(sid, prebaked_messages=db_messages)
    assert len(snapshot.messages) == 1
    assert snapshot.messages[0].content == "legacy msg"
    await engine.dispose()


def test_load_session_no_engine_uses_jsonl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """engine=None(CLI / in-memory SessionManager)→ 永遠走 JSONL。"""
    monkeypatch.setenv("ORION_SESSIONS_DIR", str(tmp_path))
    sid = uuid4()
    import anyio

    async def write() -> None:
        store = SessionStorage.open(sid)
        await store.record_meta(provider="anthropic", model="claude-sonnet-4-6")
        await store.record_message(NormalizedMessage(role="user", content="cli msg"))

    anyio.run(write)
    snapshot = load_session(sid)  # no engine = pure JSONL
    assert len(snapshot.messages) == 1
    assert snapshot.messages[0].content == "cli msg"


@pytest.mark.anyio
async def test_message_with_tool_use_block_roundtrips_via_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """複雜訊息(含 ToolUseBlock)經 DB 來回應該保留 structure。"""
    monkeypatch.setenv("ORION_SESSIONS_DIR", str(tmp_path))
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    sid = uuid4()
    await _seed_session_row(engine, str(sid), str(uuid4()))

    store = SessionStorage.open(sid, db_engine=engine)
    await store.record_meta(provider="anthropic", model="claude-sonnet-4-6")
    complex_msg = NormalizedMessage(
        role="assistant",
        content=[
            TextBlock(text="let me look"),
            ToolUseBlock(id="tu_1", name="Read", input={"path": "/x"}),
        ],
    )
    await store.record_message(complex_msg)

    db_messages = await fetch_db_messages(sid, engine)
    assert db_messages is not None
    snapshot = load_session(sid, prebaked_messages=db_messages)
    # 第一則就是原始 assistant message,含 TextBlock + ToolUseBlock。
    # load_session 會 auto-repair 補一則 synthetic tool_result(dangling tool_use),
    # 那是另一則 message,不在本測試斷言範圍。
    first = snapshot.messages[0]
    assert first.role == "assistant"
    blocks = first.content
    assert isinstance(blocks, list)
    assert len(blocks) == 2
    assert isinstance(blocks[0], TextBlock)
    assert isinstance(blocks[1], ToolUseBlock)
    assert blocks[1].name == "Read"
    await engine.dispose()


@pytest.mark.anyio
async def test_db_insert_failure_does_not_break_jsonl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DB INSERT 例外 → JSONL 仍寫入。

    用 dispose 過的 engine 模擬 DB down,確保 SessionStorage 不因 DB 失敗就放棄 JSONL。
    """
    monkeypatch.setenv("ORION_SESSIONS_DIR", str(tmp_path))
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    sid = uuid4()
    await _seed_session_row(engine, str(sid), str(uuid4()))
    await engine.dispose()  # 故意先 dispose,後續 INSERT 會炸

    store = SessionStorage.open(sid, db_engine=engine)
    await store.record_meta(provider="anthropic", model="claude-sonnet-4-6")
    await store.record_message(NormalizedMessage(role="user", content="hello"))

    # JSONL 應寫進去
    transcript = tmp_path / str(sid) / "transcript.jsonl"
    assert transcript.exists()
    assert "hello" in transcript.read_text(encoding="utf-8")


@pytest.mark.anyio
async def test_replacements_still_jsonl_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 27 沒搬 replacements 進 DB,resume 仍能拿到從 JSONL 重建的 state。"""
    monkeypatch.setenv("ORION_SESSIONS_DIR", str(tmp_path))
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    sid = uuid4()
    await _seed_session_row(engine, str(sid), str(uuid4()))

    store = SessionStorage.open(sid, db_engine=engine)
    await store.record_meta(provider="anthropic", model="claude-sonnet-4-6")
    await store.record_message(NormalizedMessage(role="user", content="hello"))
    await store.record_replacement([
        ReplacementDecision(tool_use_id="tu_x", replacement="(omitted)"),
    ])

    # transcript 內應該有 replacement record
    transcript = tmp_path / str(sid) / "transcript.jsonl"
    text = transcript.read_text(encoding="utf-8")
    assert "tool-result-replacement" in text
    await engine.dispose()
