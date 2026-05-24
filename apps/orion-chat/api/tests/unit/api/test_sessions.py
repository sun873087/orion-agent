"""api/routes/sessions.py — REST CRUD。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from orion_chat_api.app import create_app
from orion_chat_api.auth import dev_user_id


@pytest.fixture
def client_with_token(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, str]:
    """共用 fixture — login 完拿到 (client, bearer_header_token)。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key")
    monkeypatch.setenv("ORION_PROVIDER", "anthropic")
    monkeypatch.setenv("ORION_MODEL", "claude-sonnet-4-6")
    client = TestClient(create_app())
    login = client.post("/auth/login", json={"username": "alice"}).json()
    return client, login["token"]


def test_create_session(client_with_token: tuple[TestClient, str]) -> None:
    client, token = client_with_token
    r = client.post("/sessions", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 201
    body = r.json()
    # 後 user_id 是 deterministic uuid5(無 DB 路徑),不再是 username
    assert body["user_id"] == dev_user_id("alice")
    assert body["n_messages"] == 0
    assert body["n_turns"] == 0
    # 沒帶 body → 走 server default(env ORION_PROVIDER / ORION_MODEL)
    assert body["provider"] == "anthropic"
    assert body["model"] == "claude-sonnet-4-6"


def test_create_session_explicit_anthropic(
    client_with_token: tuple[TestClient, str],
) -> None:
    client, token = client_with_token
    r = client.post(
        "/sessions",
        headers={"Authorization": f"Bearer {token}"},
        json={"provider": "anthropic", "model": "claude-opus-4-7"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["provider"] == "anthropic"
    assert body["model"] == "claude-opus-4-7"


def test_create_session_explicit_openai(
    client_with_token: tuple[TestClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")
    client, token = client_with_token
    r = client.post(
        "/sessions",
        headers={"Authorization": f"Bearer {token}"},
        json={"provider": "openai", "model": "gpt-5"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["provider"] == "openai"
    assert body["model"] == "gpt-5"


def test_create_session_invalid_pair_returns_422(
    client_with_token: tuple[TestClient, str],
) -> None:
    client, token = client_with_token
    # 跨 provider — anthropic + gpt-5 不合法
    r = client.post(
        "/sessions",
        headers={"Authorization": f"Bearer {token}"},
        json={"provider": "anthropic", "model": "gpt-5"},
    )
    assert r.status_code == 422
    assert "invalid" in r.json()["detail"].lower()


def test_create_session_partial_pair_returns_422(
    client_with_token: tuple[TestClient, str],
) -> None:
    client, token = client_with_token
    r = client.post(
        "/sessions",
        headers={"Authorization": f"Bearer {token}"},
        json={"provider": "anthropic"},
    )
    assert r.status_code == 422
    assert "both" in r.json()["detail"].lower()


def test_create_session_missing_api_key_returns_503(
    client_with_token: tuple[TestClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # 沒走 proxy 才會踩 individual key 不存在的 503;有走 proxy 改另一 test 驗
    monkeypatch.delenv("ORION_MODEL_PROXY_URL", raising=False)
    monkeypatch.delenv("ORION_MODEL_PROXY_KEY", raising=False)
    client, token = client_with_token
    r = client.post(
        "/sessions",
        headers={"Authorization": f"Bearer {token}"},
        json={"provider": "openai", "model": "gpt-5"},
    )
    assert r.status_code == 503
    assert "OPENAI_API_KEY" in r.json()["detail"]


def test_create_session_proxy_mode_works_without_individual_key(
    client_with_token: tuple[TestClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """走 proxy 時 individual provider key 由 proxy server-side 保管 — client
    端只要有 ORION_MODEL_PROXY_URL + ORION_MODEL_PROXY_KEY,UI 上所有 provider
    都該 available,create_session 也不該因缺 individual key 擋下。"""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("ORION_MODEL_PROXY_URL", "http://proxy.local:9090")
    monkeypatch.setenv("ORION_MODEL_PROXY_KEY", "sk-orion-test")
    client, token = client_with_token
    r = client.post(
        "/sessions",
        headers={"Authorization": f"Bearer {token}"},
        json={"provider": "openai", "model": "gpt-5"},
    )
    assert r.status_code == 201, r.text


def test_list_models_endpoint(
    client_with_token: tuple[TestClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-anthropic-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # Direct mode 測試 — 確保 individual key 控制 availability
    monkeypatch.delenv("ORION_MODEL_PROXY_URL", raising=False)
    monkeypatch.delenv("ORION_MODEL_PROXY_KEY", raising=False)
    client, token = client_with_token
    r = client.get(
        "/models", headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    providers = {p["id"]: p for p in body["providers"]}
    assert "anthropic" in providers
    assert "openai" in providers
    assert providers["anthropic"]["available"] is True
    assert providers["openai"]["available"] is False
    # default 來自 env(client_with_token fixture 已設)
    assert body["default"]["provider"] == "anthropic"
    assert body["default"]["model"] == "claude-sonnet-4-6"
    # models list 非空
    assert len(providers["anthropic"]["models"]) >= 3
    assert len(providers["openai"]["models"]) >= 3


def test_list_models_proxy_mode_all_available(
    client_with_token: tuple[TestClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """走 proxy 時所有 provider 都該 available — UI 才不會誤灰掉。"""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("ORION_MODEL_PROXY_URL", "http://proxy.local:9090")
    monkeypatch.setenv("ORION_MODEL_PROXY_KEY", "sk-orion-test")
    client, token = client_with_token
    r = client.get("/models", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    providers = {p["id"]: p for p in r.json()["providers"]}
    # Anthropic / OpenAI / Google / OpenRouter 全 available;ollama 走本機沒 proxy 概念
    for pid in ("anthropic", "openai", "google", "openrouter"):
        if pid in providers:
            assert providers[pid]["available"] is True, f"{pid} should be available via proxy"


def test_list_sessions_empty(client_with_token: tuple[TestClient, str]) -> None:
    client, token = client_with_token
    r = client.get("/sessions", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json() == []


def test_list_after_create(client_with_token: tuple[TestClient, str]) -> None:
    client, token = client_with_token
    client.post("/sessions", headers={"Authorization": f"Bearer {token}"})
    client.post("/sessions", headers={"Authorization": f"Bearer {token}"})
    r = client.get("/sessions", headers={"Authorization": f"Bearer {token}"})
    assert len(r.json()) == 2


def test_get_session_by_id(client_with_token: tuple[TestClient, str]) -> None:
    client, token = client_with_token
    sid = client.post(
        "/sessions", headers={"Authorization": f"Bearer {token}"},
    ).json()["session_id"]
    r = client.get(
        f"/sessions/{sid}", headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["session_id"] == sid


def test_get_nonexistent_returns_404(client_with_token: tuple[TestClient, str]) -> None:
    client, token = client_with_token
    r = client.get(
        "/sessions/00000000-0000-0000-0000-000000000000",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404


def test_delete_session(client_with_token: tuple[TestClient, str]) -> None:
    client, token = client_with_token
    sid = client.post(
        "/sessions", headers={"Authorization": f"Bearer {token}"},
    ).json()["session_id"]
    r = client.delete(
        f"/sessions/{sid}", headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 204
    # 第二次刪 404
    r2 = client.delete(
        f"/sessions/{sid}", headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 404


def test_user_isolation(client_with_token: tuple[TestClient, str]) -> None:
    """user A 的 session 不該被 user B 看到。"""
    client, token_a = client_with_token
    sid_a = client.post(
        "/sessions", headers={"Authorization": f"Bearer {token_a}"},
    ).json()["session_id"]

    token_b = client.post("/auth/login", json={"username": "bob"}).json()["token"]
    r = client.get(
        f"/sessions/{sid_a}", headers={"Authorization": f"Bearer {token_b}"},
    )
    assert r.status_code == 404

    list_b = client.get(
        "/sessions", headers={"Authorization": f"Bearer {token_b}"},
    ).json()
    assert list_b == []
