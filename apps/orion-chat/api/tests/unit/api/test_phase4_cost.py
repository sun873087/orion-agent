"""Phase 4 — context breakdown(讀)。

cost breakdown 沿用既有 /cost 的 by_model;turn audit / message feedback 因架構
(WS 串流無穩定 message id、SDK 未 expose wire payload)延後,見路線圖。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orion_chat_api.app import create_app


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


def test_cost_endpoint_exposes_real_top_level_tokens(
    client_with_token: tuple[TestClient, str],
) -> None:
    """/cost 要把跨 model 的真實 token 攤平到頂層(不是 chars/4 概估)。"""
    from orion_sdk.telemetry.cost_tracker import get_or_create_tracker

    client, token = client_with_token
    sid = client.post("/sessions", headers=_h(token)).json()["session_id"]
    tr = get_or_create_tracker(sid)
    tr.record(
        model="claude-sonnet-4-6",
        input_tokens=1200,
        output_tokens=80,
        cache_read_tokens=300,
    )
    body = client.get(f"/sessions/{sid}/cost", headers=_h(token)).json()
    assert body["input_tokens"] == 1200
    assert body["output_tokens"] == 80
    assert body["cache_read_tokens"] == 300
    assert body["total_cost_usd"] > 0  # 由真實 token × 定價算出


def test_cost_endpoint_returns_by_origin(
    client_with_token: tuple[TestClient, str],
) -> None:
    """/cost 要 by-origin 細分(chat / title / follow_ups),對齊 cowork。"""
    from orion_sdk.telemetry.cost_tracker import get_or_create_tracker

    client, token = client_with_token
    sid = client.post("/sessions", headers=_h(token)).json()["session_id"]
    tr = get_or_create_tracker(sid)
    tr.record(
        model="claude-sonnet-4-6", origin="chat",
        input_tokens=1000, output_tokens=200,
    )
    tr.record(
        model="claude-sonnet-4-6", origin="title",
        input_tokens=300, output_tokens=10,
    )
    body = client.get(f"/sessions/{sid}/cost", headers=_h(token)).json()
    assert set(body["by_origin"]) == {"chat", "title"}
    assert body["by_origin"]["title"]["input_tokens"] == 300
    assert body["by_origin"]["chat"]["cost_usd"] > 0


def test_context_breakdown_shape(
    client_with_token: tuple[TestClient, str],
) -> None:
    client, token = client_with_token
    sid = client.post("/sessions", headers=_h(token)).json()["session_id"]
    r = client.get(f"/sessions/{sid}/context-breakdown", headers=_h(token))
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["n_messages"] == 0
    assert body["by_role_chars"] == {}
    assert isinstance(body["approx_total_tokens"], int)
    assert body["approx_total_tokens"] >= 0


def test_context_breakdown_404_for_missing(
    client_with_token: tuple[TestClient, str],
) -> None:
    client, token = client_with_token
    r = client.get(
        "/sessions/00000000-0000-0000-0000-000000000000/context-breakdown",
        headers=_h(token),
    )
    assert r.status_code == 404
