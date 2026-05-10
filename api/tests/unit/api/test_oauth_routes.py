"""/oauth/* end-to-end via dev-mock provider。Phase 25。

dev-mock 不打外部 — start_web_oauth_flow 直接回 callback URL,callback 自行短路寫
fake token。整個 flow 可離線跑。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from orion_agent.api.app import create_app
from orion_agent.mcp import oauth as oauth_mod
from orion_agent.storage.secure import EncryptedFileBackend


@pytest.fixture
def client_with_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> Iterator[tuple[TestClient, str]]:
    """每個 test 用獨立 EncryptedFileBackend(tmp_path),避免污染 keychain。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key")
    monkeypatch.setenv("ORION_PROVIDER", "anthropic")
    monkeypatch.setenv("ORION_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("ORION_DB_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("ORION_DB_AUTO_CREATE", "1")
    # 強制不走 keychain,寫進 tmp 加密檔
    backend = EncryptedFileBackend(tmp_path / "secrets.enc")
    oauth_mod.reset_backend_for_tests(backend)
    try:
        with TestClient(create_app()) as client:
            client.post(
                "/auth/register",
                json={"username": "alice", "password": "passw0rd"},
            )
            login = client.post(
                "/auth/login",
                json={"username": "alice", "password": "passw0rd"},
            ).json()
            yield client, login["token"]
    finally:
        oauth_mod.reset_backend_for_tests(None)


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_list_providers_includes_dev_mock(
    client_with_token: tuple[TestClient, str],
) -> None:
    client, token = client_with_token
    r = client.get("/oauth/providers", headers=_h(token))
    assert r.status_code == 200
    names = {p["name"] for p in r.json()}
    assert {"dev-mock", "github", "linear", "google", "microsoft"} <= names


def test_google_authorize_url_has_offline_access_params(
    client_with_token: tuple[TestClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Google 必須帶 access_type=offline + prompt=consent 才會回 refresh_token。"""
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "fake-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "fake-secret")
    client, token = client_with_token
    r = client.post(
        "/oauth/start", headers=_h(token), json={"server": "google"},
    )
    assert r.status_code == 200, r.json()
    url = r.json()["authorize_url"]
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    assert parsed.netloc == "accounts.google.com"
    assert qs["access_type"] == ["offline"]
    assert qs["prompt"] == ["consent"]
    assert qs["response_type"] == ["code"]
    assert qs["client_id"] == ["fake-client-id"]
    assert "openid" in qs["scope"][0]


def test_microsoft_authorize_url_has_offline_access_scope(
    client_with_token: tuple[TestClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Microsoft 必須包含 offline_access scope 才會回 refresh_token。"""
    monkeypatch.setenv("MICROSOFT_OAUTH_CLIENT_ID", "fake-client-id")
    monkeypatch.setenv("MICROSOFT_OAUTH_CLIENT_SECRET", "fake-secret")
    client, token = client_with_token
    r = client.post(
        "/oauth/start", headers=_h(token), json={"server": "microsoft"},
    )
    assert r.status_code == 200, r.json()
    url = r.json()["authorize_url"]
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    assert "login.microsoftonline.com" in parsed.netloc
    assert "/common/oauth2/v2.0/authorize" in parsed.path
    assert "offline_access" in qs["scope"][0].split()
    assert "User.Read" in qs["scope"][0].split()


def test_status_unconfigured_provider(
    client_with_token: tuple[TestClient, str],
) -> None:
    """github 沒設 env → available=False, connected=False。"""
    client, token = client_with_token
    r = client.get("/oauth/status/github", headers=_h(token))
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["connected"] is False


def test_full_dev_mock_flow(
    client_with_token: tuple[TestClient, str],
) -> None:
    """start → callback → status 應從 false → true。"""
    client, token = client_with_token

    # start
    r = client.post(
        "/oauth/start", headers=_h(token), json={"server": "dev-mock"},
    )
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["state"]
    parsed = urlparse(body["authorize_url"])
    qs = parse_qs(parsed.query)
    assert qs["state"] == [body["state"]]
    assert qs["code"] == ["dev-mock-code"]

    # callback (TestClient follow-up GET)
    cb = client.get(
        "/oauth/callback",
        params={"state": body["state"], "code": "dev-mock-code"},
    )
    assert cb.status_code == 200
    assert "Connected to dev-mock" in cb.text

    # status now connected
    s = client.get("/oauth/status/dev-mock", headers=_h(token))
    assert s.status_code == 200
    assert s.json()["connected"] is True


def test_callback_invalid_state_returns_400(
    client_with_token: tuple[TestClient, str],
) -> None:
    client, _ = client_with_token
    r = client.get(
        "/oauth/callback", params={"state": "bogus", "code": "x"},
    )
    assert r.status_code == 400
    assert "Invalid or expired" in r.text


def test_state_one_shot(
    client_with_token: tuple[TestClient, str],
) -> None:
    """一個 state 只能換一次 token — 重 callback 應 400。"""
    client, token = client_with_token
    state = client.post(
        "/oauth/start", headers=_h(token), json={"server": "dev-mock"},
    ).json()["state"]
    r1 = client.get(
        "/oauth/callback", params={"state": state, "code": "dev-mock-code"},
    )
    assert r1.status_code == 200
    r2 = client.get(
        "/oauth/callback", params={"state": state, "code": "dev-mock-code"},
    )
    assert r2.status_code == 400


def test_disconnect(
    client_with_token: tuple[TestClient, str],
) -> None:
    client, token = client_with_token
    state = client.post(
        "/oauth/start", headers=_h(token), json={"server": "dev-mock"},
    ).json()["state"]
    client.get(
        "/oauth/callback", params={"state": state, "code": "dev-mock-code"},
    )
    assert client.get(
        "/oauth/status/dev-mock", headers=_h(token),
    ).json()["connected"] is True

    r = client.delete("/oauth/dev-mock", headers=_h(token))
    assert r.status_code == 200
    assert r.json() == {"disconnected": True}
    assert client.get(
        "/oauth/status/dev-mock", headers=_h(token),
    ).json()["connected"] is False


def test_start_unknown_provider_400(
    client_with_token: tuple[TestClient, str],
) -> None:
    client, token = client_with_token
    r = client.post(
        "/oauth/start", headers=_h(token), json={"server": "no-such-thing"},
    )
    assert r.status_code == 400


def test_start_unconfigured_provider_400(
    client_with_token: tuple[TestClient, str],
) -> None:
    """github 沒設 client_id env → 400(non-mock provider)。"""
    client, token = client_with_token
    r = client.post(
        "/oauth/start", headers=_h(token), json={"server": "github"},
    )
    assert r.status_code == 400
    assert "GITHUB_OAUTH_CLIENT_ID" in r.json()["detail"]


def test_per_user_token_isolation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """alice connect 後,bob 的 status 應仍 False。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key")
    monkeypatch.setenv("ORION_PROVIDER", "anthropic")
    monkeypatch.setenv("ORION_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("ORION_DB_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("ORION_DB_AUTO_CREATE", "1")
    backend = EncryptedFileBackend(tmp_path / "secrets.enc")
    oauth_mod.reset_backend_for_tests(backend)
    try:
        with TestClient(create_app()) as client:
            for uname in ("alice", "bob"):
                client.post(
                    "/auth/register",
                    json={"username": uname, "password": "passw0rd"},
                )
            alice_t = client.post(
                "/auth/login", json={"username": "alice", "password": "passw0rd"},
            ).json()["token"]
            bob_t = client.post(
                "/auth/login", json={"username": "bob", "password": "passw0rd"},
            ).json()["token"]

            state = client.post(
                "/oauth/start", headers=_h(alice_t), json={"server": "dev-mock"},
            ).json()["state"]
            client.get(
                "/oauth/callback",
                params={"state": state, "code": "dev-mock-code"},
            )

            assert client.get(
                "/oauth/status/dev-mock", headers=_h(alice_t),
            ).json()["connected"] is True
            assert client.get(
                "/oauth/status/dev-mock", headers=_h(bob_t),
            ).json()["connected"] is False
    finally:
        oauth_mod.reset_backend_for_tests(None)


async def test_token_payload_stored_as_json(
    client_with_token: tuple[TestClient, str], tmp_path: Path,
) -> None:
    """SecureStorage 內容是 JSON,含 access_token。

    白盒 — 直接讀 backend 內容,不從 API。
    """
    client, token = client_with_token
    state = client.post(
        "/oauth/start", headers=_h(token), json={"server": "dev-mock"},
    ).json()["state"]
    client.get(
        "/oauth/callback", params={"state": state, "code": "dev-mock-code"},
    )
    # backend 是 fixture inject 的;從 module global 拿
    backend = oauth_mod._storage  # type: ignore[attr-defined]
    assert backend is not None
    raw = await backend.get("mcp:dev-mock:alice")
    assert raw is not None
    payload = json.loads(raw)
    assert payload["access_token"] == "dev-mock-token-alice"
