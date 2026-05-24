"""Phase 2 — session metadata:migration / title side-query / rename / star。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from orion_chat_api.app import create_app
from orion_chat_api.title_gen import generate_session_title, mini_provider_for


@pytest.fixture
def client_with_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> Iterator[tuple[TestClient, str]]:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key")
    monkeypatch.setenv("ORION_PROVIDER", "anthropic")
    monkeypatch.setenv("ORION_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("ORION_DB_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("ORION_DB_AUTO_CREATE", "1")
    monkeypatch.setenv("ORION_USERS_DIR", str(tmp_path / "users"))
    with TestClient(create_app()) as client:
        client.post("/auth/register", json={"username": "alice", "password": "pw123456"})
        token = client.post(
            "/auth/login", json={"username": "alice", "password": "pw123456"},
        ).json()["token"]
        yield client, token


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── migration ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_migration_adds_missing_column(tmp_path: Path) -> None:
    """_add_missing_columns 對缺欄位的既有表補上 starred。"""
    from orion_sdk.storage.db.engine import _add_missing_columns, create_db_engine

    eng = create_db_engine(f"sqlite+aiosqlite:///{tmp_path}/m.db")
    async with eng.begin() as conn:
        # 造一個「舊版」conversation_metadata(只有 session_id + title,缺 starred)
        await conn.exec_driver_sql(
            "CREATE TABLE conversation_metadata "
            "(session_id VARCHAR(36) PRIMARY KEY, title VARCHAR(255))",
        )
        await conn.run_sync(_add_missing_columns)
        cols = await conn.run_sync(
            lambda c: {col["name"] for col in inspect(c).get_columns(
                "conversation_metadata",
            )},
        )
    await eng.dispose()
    assert "starred" in cols
    assert "custom_instructions" in cols


# ── title side-query ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_session_title() -> None:
    from orion_sdk._testing import MockProvider, MockTurn

    mp = MockProvider(turns=[MockTurn(text="Trip planning to Japan")])
    title = await generate_session_title(mp, "help plan a trip", "sure!")
    assert title == "Trip planning to Japan"


@pytest.mark.asyncio
async def test_generate_session_title_empty_returns_none() -> None:
    from orion_sdk._testing import MockProvider

    mp = MockProvider(turns=[])  # 空 turn → 無文字
    assert await generate_session_title(mp, "hi", "") is None


def test_mini_provider_maps_to_haiku() -> None:
    from orion_model.provider import get_provider

    base = get_provider("anthropic", "claude-sonnet-4-6")
    mini = mini_provider_for(base)
    assert mini.model == "claude-haiku-4-5"


# ── rename / star ──────────────────────────────────────────────────────────


def test_patch_rename_and_star(
    client_with_token: tuple[TestClient, str],
) -> None:
    client, token = client_with_token
    sid = client.post("/sessions", headers=_h(token)).json()["session_id"]

    r = client.patch(f"/sessions/{sid}", headers=_h(token), json={"title": "My chat"})
    assert r.status_code == 200, r.json()
    assert r.json()["title"] == "My chat"

    # star 不該動到 title
    r2 = client.patch(f"/sessions/{sid}", headers=_h(token), json={"starred": True})
    assert r2.json()["starred"] is True
    assert r2.json()["title"] == "My chat"

    # GET /sessions 帶 title + starred
    listing = client.get("/sessions", headers=_h(token)).json()
    mine = next(s for s in listing if s["session_id"] == sid)
    assert mine["title"] == "My chat"
    assert mine["starred"] is True


def test_patch_cross_user_404(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
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
        sid = client.post("/sessions", headers=_h(at)).json()["session_id"]
        r = client.patch(f"/sessions/{sid}", headers=_h(bt), json={"title": "hijack"})
        assert r.status_code == 404
