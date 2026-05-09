"""api/routes/chat.py — WebSocket integration。

用 fastapi.testclient 的 websocket_connect 跑完整 round-trip。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from orion_agent.api.app import create_app


@pytest.fixture
def app_with_mock_provider(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """把 LLMProvider 替成 MockProvider。"""
    from tests.conftest import MockProvider, MockTurn

    app = create_app()
    # 在 app.state 替換,蓋過 _provider_from_env
    app.state.llm_provider = MockProvider(turns=[
        MockTurn(text="hello back from mock"),
    ])
    return TestClient(app)


def _login(client: TestClient, username: str = "alice") -> str:
    return client.post("/auth/login", json={"username": username}).json()["token"]


@contextmanager
def _session(client: TestClient, token: str) -> Iterator[tuple[str, str]]:
    """建 session + ws,回 (session_id, token)。"""
    r = client.post("/sessions", headers={"Authorization": f"Bearer {token}"})
    sid = r.json()["session_id"]
    yield sid, token


def test_ws_user_message_full_flow(app_with_mock_provider: TestClient) -> None:
    client = app_with_mock_provider
    token = _login(client)
    with _session(client, token) as (sid, _), client.websocket_connect(
        f"/chat/stream/{sid}?token={token}",
    ) as ws:
        ws.send_json({"type": "user_message", "content": "hi"})

        events = []
        # 收到 terminal 為止
        while True:
            ev = ws.receive_json()
            events.append(ev)
            if ev["type"] == "terminal":
                break

        types = [e["type"] for e in events]
        # 應有:assistant_text(streaming)→ turn_complete → terminal
        assert "assistant_text" in types
        assert "turn_complete" in types
        assert types[-1] == "terminal"

        # assistant_text 累積應含 mock provider 回的內容
        text = "".join(e["text"] for e in events if e["type"] == "assistant_text")
        assert "hello back from mock" in text


def test_ws_invalid_token_closes_connection(app_with_mock_provider: TestClient) -> None:
    client = app_with_mock_provider
    valid = _login(client)
    with (
        _session(client, valid) as (sid, _),
        pytest.raises(Exception),  # noqa: B017
        client.websocket_connect(f"/chat/stream/{sid}?token=garbage") as ws,
    ):
        ws.receive_json()  # 應該收不到,被 close


def test_ws_unknown_session_auto_created(app_with_mock_provider: TestClient) -> None:
    """ws 用沒建過的 session_id 應自動建。"""
    from uuid import uuid4

    client = app_with_mock_provider
    token = _login(client)
    new_sid = str(uuid4())

    with client.websocket_connect(
        f"/chat/stream/{new_sid}?token={token}",
    ) as ws:
        # 連線時 server 先送 history_replay_done(空 history)
        first = ws.receive_json()
        assert first["type"] == "history_replay_done"
        ws.send_json({"type": "user_message", "content": "hi"})
        # 收到任何 server event 即表示 ws 通了
        ev = ws.receive_json()
        assert "type" in ev


def test_ws_bad_client_event_emits_error(app_with_mock_provider: TestClient) -> None:
    client = app_with_mock_provider
    token = _login(client)
    with _session(client, token) as (sid, _), client.websocket_connect(
        f"/chat/stream/{sid}?token={token}",
    ) as ws:
        # 連線時 server 會先送 history_replay_done(空 history)
        first = ws.receive_json()
        assert first["type"] == "history_replay_done"
        ws.send_json({"type": "garbage"})
        ev = ws.receive_json()
        assert ev["type"] == "error"
