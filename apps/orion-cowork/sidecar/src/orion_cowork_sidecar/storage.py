"""Cowork local SQLite persistence(Phase 31-D)。

跟 chat-api 的 DbSessionManager 不同:
- Single-user 模式 — 用固定 dummy user "cowork-local"
- 不依賴 fastapi / jwt(只用 orion-sdk storage primitives)
- DB 位置:`~/.orion-cowork/sessions.db`(macOS / Linux),
            `%LOCALAPPDATA%\\Orion Cowork\\sessions.db`(Windows),
            `$ORION_COWORK_DATA_DIR/sessions.db`(e2e 用)

Public API:
    init_storage() -> engine                   # call once at startup
    save_session_metadata(engine, sid, ...)
    update_title_if_empty(engine, sid, title)
    list_sessions(engine) -> list[SessionMeta]
    delete_session(engine, sid)
    append_messages(engine, sid, messages)
    load_messages(engine, sid) -> list[NormalizedMessage]
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine

from orion_model.types import NormalizedMessage
from orion_sdk.storage.db.engine import create_db_engine, db_session, init_db
from orion_sdk.storage.db.models import ConversationMetadata as MetaRow
from orion_sdk.storage.db.models import Message as MessageRow
from orion_sdk.storage.db.models import Session as SessionRow
from orion_sdk.storage.db.models import User as UserRow
from orion_sdk.storage.resume import _message_from_dict as _msg_from_dict

LOCAL_USER_ID = "cowork-local"
LOCAL_USERNAME = "local"


def data_dir() -> Path:
    """Cowork user data root,可由 ORION_COWORK_DATA_DIR env 覆蓋。"""
    env = os.environ.get("ORION_COWORK_DATA_DIR")
    if env:
        return Path(env)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Orion Cowork"
    return Path.home() / ".orion-cowork"


def _db_url() -> str:
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{d / 'sessions.db'}"


async def init_storage() -> AsyncEngine:
    """Init engine + migrations + dummy user。Idempotent。"""
    engine = create_db_engine(_db_url())
    await init_db(engine)
    await _upsert_local_user(engine)
    return engine


async def _upsert_local_user(engine: AsyncEngine) -> None:
    async with db_session(engine) as s:
        existing = await s.get(UserRow, LOCAL_USER_ID)
        if existing is None:
            s.add(UserRow(
                id=LOCAL_USER_ID,
                username=LOCAL_USERNAME,
                password_hash="$2b$12$cowork.local.no.password.................",
            ))
            await s.commit()


@dataclass
class SessionMeta:
    session_id: str
    provider: str
    model: str
    title: str | None
    created_at: float
    n_messages: int


async def save_session_metadata(
    engine: AsyncEngine,
    session_id: str,
    *,
    provider: str,
    model: str,
) -> None:
    """Insert SessionRow + empty ConversationMetadata(idempotent)。"""
    async with db_session(engine) as s:
        row = await s.get(SessionRow, session_id)
        if row is None:
            s.add(SessionRow(
                id=session_id,
                user_id=LOCAL_USER_ID,
                provider=provider,
                model=model,
            ))
        else:
            row.provider = provider
            row.model = model

        meta = await s.get(MetaRow, session_id)
        if meta is None:
            s.add(MetaRow(session_id=session_id))
        await s.commit()


async def update_title_if_empty(engine: AsyncEngine, session_id: str, title: str) -> None:
    async with db_session(engine) as s:
        meta = await s.get(MetaRow, session_id)
        if meta is None:
            return
        if meta.title:
            return
        meta.title = title[:60].strip()
        await s.commit()


async def list_sessions(engine: AsyncEngine) -> list[SessionMeta]:
    async with db_session(engine) as s:
        stmt = (
            select(SessionRow)
            .where(SessionRow.user_id == LOCAL_USER_ID)
            .order_by(SessionRow.created_at.desc())
        )
        rows = list((await s.execute(stmt)).scalars())

        out: list[SessionMeta] = []
        for r in rows:
            meta = await s.get(MetaRow, r.id)
            title = meta.title if meta is not None else None
            count_stmt = select(MessageRow.id).where(MessageRow.session_id == r.id)
            n = len(list((await s.execute(count_stmt)).scalars()))
            out.append(SessionMeta(
                session_id=r.id,
                provider=r.provider or "anthropic",
                model=r.model or "claude-sonnet-4-6",
                title=title,
                created_at=r.created_at.timestamp() if r.created_at else time.time(),
                n_messages=n,
            ))
        return out


async def delete_session(engine: AsyncEngine, session_id: str) -> bool:
    async with db_session(engine) as s:
        row = await s.get(SessionRow, session_id)
        if row is None:
            return False
        # Explicit cascade(避免 SQLite FK 設定差異 — CASCADE 也設了 ondelete)
        await s.execute(delete(MessageRow).where(MessageRow.session_id == session_id))
        await s.execute(delete(MetaRow).where(MetaRow.session_id == session_id))
        await s.delete(row)
        await s.commit()
        return True


async def append_messages(
    engine: AsyncEngine,
    session_id: str,
    messages: list[NormalizedMessage],
) -> None:
    """Append 新訊息(caller 負責不重複)。"""
    if not messages:
        return
    async with db_session(engine) as s:
        for msg in messages:
            content_value: Any
            content = msg.content
            if isinstance(content, str):
                content_value = content
            else:
                content_value = [b.model_dump(mode="json") for b in content]
            s.add(MessageRow(
                session_id=session_id,
                role=msg.role,
                content_json=content_value,
            ))
        await s.commit()


async def load_messages(
    engine: AsyncEngine,
    session_id: str,
) -> list[NormalizedMessage]:
    async with db_session(engine) as s:
        stmt = (
            select(MessageRow.role, MessageRow.content_json)
            .where(MessageRow.session_id == session_id)
            .order_by(MessageRow.created_at, MessageRow.id)
        )
        rows = list(await s.execute(stmt))
    out: list[NormalizedMessage] = []
    for role, content_json in rows:
        msg = _msg_from_dict({"role": role, "content": content_json})
        if msg is not None:
            out.append(msg)
    return out
