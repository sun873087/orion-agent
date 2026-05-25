"""Schedules 真的會 fire — run-now 端點實際開 session 跑一輪;daemon 隨 DB 啟動。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from orion_chat_api.app import create_app


def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, daemon: bool) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key")
    monkeypatch.setenv("ORION_PROVIDER", "anthropic")
    monkeypatch.setenv("ORION_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("ORION_DB_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("ORION_DB_AUTO_CREATE", "1")
    monkeypatch.setenv("ORION_USERS_DIR", str(tmp_path / "users"))
    # 多數測試關背景 daemon,避免 tick task 干擾;只有 daemon 測試開
    monkeypatch.setenv("ORION_DISABLE_SCHEDULER", "0" if daemon else "1")


def test_run_now_actually_runs_a_turn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from orion_sdk._testing import MockProvider, MockTurn

    _env(monkeypatch, tmp_path, daemon=False)
    app = create_app()
    with TestClient(app) as client:
        client.app.state.llm_provider = MockProvider(
            turns=[MockTurn(text="done"), MockTurn(text="done")],
        )
        client.post("/auth/register", json={"username": "a", "password": "pw123456"})
        token = client.post(
            "/auth/login", json={"username": "a", "password": "pw123456"},
        ).json()["token"]
        h = {"Authorization": f"Bearer {token}"}

        before = len(client.get("/sessions", headers=h).json())
        sched = client.post(
            "/schedules",
            headers=h,
            json={
                "name": "daily",
                "cron_expr": "0 9 * * *",
                "trigger_type": "prompt",
                "payload": "summarise my day",
            },
        ).json()

        r = client.post(f"/schedules/{sched['id']}/run-now", headers=h)
        assert r.status_code == 200, r.text
        sid = r.json()["session_id"]
        assert sid, "run-now did not produce a session"

        # 真的開了新 session + provider 真的被呼叫(turn 真的跑)
        after = client.get("/sessions", headers=h).json()
        assert len(after) == before + 1
        assert client.app.state.llm_provider.captured_calls, "provider not called"


def test_run_now_cross_user_404(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _env(monkeypatch, tmp_path, daemon=False)
    app = create_app()
    with TestClient(app) as client:
        client.post("/auth/register", json={"username": "a", "password": "pw123456"})
        ta = client.post(
            "/auth/login", json={"username": "a", "password": "pw123456"},
        ).json()["token"]
        sched = client.post(
            "/schedules",
            headers={"Authorization": f"Bearer {ta}"},
            json={"name": "x", "cron_expr": "0 9 * * *", "payload": "hi"},
        ).json()
        client.post("/auth/register", json={"username": "b", "password": "pw123456"})
        tb = client.post(
            "/auth/login", json={"username": "b", "password": "pw123456"},
        ).json()["token"]
        r = client.post(
            f"/schedules/{sched['id']}/run-now",
            headers={"Authorization": f"Bearer {tb}"},
        )
        assert r.status_code == 404


def test_scheduler_daemon_starts_with_db(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _env(monkeypatch, tmp_path, daemon=True)
    app = create_app()
    with TestClient(app):
        sched: Any = getattr(app.state, "scheduler", None)
        assert sched is not None, "background scheduler did not start"
        assert sched._task is not None
