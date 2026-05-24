"""Phase 3 — fork / truncate / regenerate / compact。

fork / truncate 的核心邏輯在 DbSessionManager,直接 async 測(免 HTTP/LLM)。
route 層的 ownership(跨 user 404)用 TestClient 測。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from orion_chat_api.app import create_app


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_fork_and_truncate(tmp_path: Path) -> None:
    from orion_chat_api.session_manager_db import DbSessionManager
    from orion_model.provider import get_provider
    from orion_model.types import NormalizedMessage
    from orion_sdk.core.conversation import Conversation
    from orion_sdk.storage.db.engine import create_db_engine, db_session, init_db
    from orion_sdk.storage.db.models import Message as MessageRow, User

    eng = create_db_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await init_db(eng)
    uid = str(uuid4())
    async with db_session(eng) as db:
        db.add(User(id=uid, username="u", password_hash="x"))
        await db.commit()

    sm = DbSessionManager(engine=eng)
    sid = uuid4()
    conv = Conversation(
        provider=get_provider("anthropic", "claude-sonnet-4-6"),
        user_id=uid,
        session_id=sid,
        state_messages=[
            NormalizedMessage(role="user", content="hi"),
            NormalizedMessage(role="assistant", content="hello"),
            NormalizedMessage(role="user", content="more"),
            NormalizedMessage(role="assistant", content="ok"),
        ],
        db_engine=eng,
        include_workspace_context=False,
    )
    await sm.create(user_id=uid, session_id=sid, conversation=conv)

    # fork 前兩則
    new_sid = await sm.fork_session(uid, sid, 2, "Forked")
    assert new_sid is not None
    new_conv = await sm.get(uid, new_sid)
    assert new_conv is not None and len(new_conv.state_messages) == 2
    async with db_session(eng) as db:
        rows = (
            await db.execute(
                select(MessageRow).where(MessageRow.session_id == str(new_sid)),
            )
        ).scalars().all()
    assert len(rows) == 2
    # 原 session 不變
    assert len(conv.state_messages) == 4

    # truncate 原 session 到 1
    n = await sm.truncate_session(uid, sid, 1)
    assert n == 1
    assert len(conv.state_messages) == 1
    async with db_session(eng) as db:
        rows = (
            await db.execute(
                select(MessageRow).where(MessageRow.session_id == str(sid)),
            )
        ).scalars().all()
    assert len(rows) == 1
    await eng.dispose()


@pytest.fixture
def two_users(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> Iterator[tuple[TestClient, str, str]]:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key")
    monkeypatch.setenv("ORION_PROVIDER", "anthropic")
    monkeypatch.setenv("ORION_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("ORION_DB_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("ORION_DB_AUTO_CREATE", "1")
    monkeypatch.setenv("ORION_USERS_DIR", str(tmp_path / "users"))
    with TestClient(create_app()) as client:
        for u in ("alice", "bob"):
            client.post("/auth/register", json={"username": u, "password": "pw123456"})
        at = client.post(
            "/auth/login", json={"username": "alice", "password": "pw123456"},
        ).json()["token"]
        bt = client.post(
            "/auth/login", json={"username": "bob", "password": "pw123456"},
        ).json()["token"]
        yield client, at, bt


def test_fork_cross_user_404(two_users: tuple[TestClient, str, str]) -> None:
    client, at, bt = two_users
    sid = client.post("/sessions", headers=_h(at)).json()["session_id"]
    r = client.post(f"/sessions/{sid}/fork", headers=_h(bt), json={})
    assert r.status_code == 404


def test_fork_empty_session_via_route(two_users: tuple[TestClient, str, str]) -> None:
    """fork 空 session(整段)→ 回新 session(201),屬同 user。"""
    client, at, _ = two_users
    sid = client.post("/sessions", headers=_h(at)).json()["session_id"]
    r = client.post(f"/sessions/{sid}/fork", headers=_h(at), json={"title": "Branch"})
    assert r.status_code == 201, r.json()
    body = r.json()
    assert body["session_id"] != sid
    assert body["title"] == "Branch"
    # 出現在 alice 的 list
    ids = {s["session_id"] for s in client.get("/sessions", headers=_h(at)).json()}
    assert body["session_id"] in ids
