"""MCP OAuth — Phase 25 web flow (Anthropic-style authorization code).

Phase 5 留了 stub raise NotImplementedError;Phase 25 接通到讓 Settings → Connections
分頁可以走完一次完整 OAuth:

  user → Connect → window.open(authorize_url + state) → 第三方授權 → 回 callback URL
  → 後端 POST token_url 換 access_token → SecureStorage.set(`mcp:<server>:<uid>`, token)
  → callback render close-window HTML → 前端 polling /oauth/status/<server> 看到
  connected=true → 顯示 ✓

設計取捨:

- **不黏死 provider list**:`OAuthProvider` 是 dataclass + module-level registry。
  內建 `dev-mock`(離線 e2e 測用)+ GitHub + Linear 兩個範例,前提是設好對應的
  `<NAME>_OAUTH_CLIENT_ID` / `_SECRET` env。沒設 env 的 provider 會在 list 中
  標 `unavailable=True`,前端 disable Connect 按鈕。

- **state store in-memory**:OAuth state token 是 5-min TTL random uuid。多 worker
  / 重啟會掉,但 OAuth flow 本來就短(< 1 min),且重啟掉 state 比寫進 DB 簡單;
  production 真要跨 worker 分享改 Redis 是後續 phase 的事。

- **token 存 SecureStorage**:Phase 14 的 keychain / encrypted-file backend。Key
  格式 `mcp:<server>:<user_id>`,值是 JSON `{access_token, refresh_token?, expires_at?, raw}`。
  refresh 邏輯 deferred — Phase 25 範圍只到取得 token + 持久化。

- **`dev-mock` provider**:實作 `start_web_oauth_flow` 時若 server 是 dev-mock,
  authorize_url 直接打回 callback URL 帶 `code=dev-mock-code`,callback 不打外部
  token endpoint,直接寫一個固定 fake token。這讓 unit test 不用 stub httpx。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx

from orion_agent.storage.secure import SecureStorageBackend, create_backend

logger = logging.getLogger(__name__)


# ─── Provider registry ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OAuthProvider:
    """單一 OAuth 2.0 provider 設定(authorization code flow)。"""

    name: str
    """user-facing 短名,也是 storage key 與 URL path segment。"""
    label: str
    """UI 顯示名(例如 'GitHub')。"""
    authorize_url: str
    """authorization endpoint。"""
    token_url: str
    """token exchange endpoint(POST)。"""
    scopes: list[str] = field(default_factory=list)
    client_id_env: str | None = None
    """env var 名稱;None → 不需要 client(目前只有 dev-mock)。"""
    client_secret_env: str | None = None

    def client_id(self) -> str | None:
        if self.client_id_env is None:
            return None
        return os.environ.get(self.client_id_env)

    def client_secret(self) -> str | None:
        if self.client_secret_env is None:
            return None
        return os.environ.get(self.client_secret_env)

    def available(self) -> bool:
        """env 是否齊全(dev-mock 不需要 env,永遠 available)。"""
        if self.client_id_env is None:
            return True
        return bool(self.client_id() and self.client_secret())


_BUILTIN_PROVIDERS: list[OAuthProvider] = [
    OAuthProvider(
        name="dev-mock",
        label="Dev Mock",
        authorize_url="",  # 不打外部,callback 自行短路
        token_url="",
        scopes=[],
    ),
    OAuthProvider(
        name="github",
        label="GitHub",
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        scopes=["repo", "read:user"],
        client_id_env="GITHUB_OAUTH_CLIENT_ID",
        client_secret_env="GITHUB_OAUTH_CLIENT_SECRET",
    ),
    OAuthProvider(
        name="linear",
        label="Linear",
        authorize_url="https://linear.app/oauth/authorize",
        token_url="https://api.linear.app/oauth/token",
        scopes=["read", "write"],
        client_id_env="LINEAR_OAUTH_CLIENT_ID",
        client_secret_env="LINEAR_OAUTH_CLIENT_SECRET",
    ),
]


def list_providers() -> list[OAuthProvider]:
    """回所有已知 provider(含 unavailable)。前端 list 用。"""
    return list(_BUILTIN_PROVIDERS)


def get_provider(name: str) -> OAuthProvider | None:
    for p in _BUILTIN_PROVIDERS:
        if p.name == name:
            return p
    return None


# ─── State store(in-memory,TTL 5 min)───────────────────────────────────────


_STATE_TTL_SECONDS = 300


@dataclass
class _StateRecord:
    server_name: str
    user_id: str
    redirect_uri: str
    created_at: float


_state_store: dict[str, _StateRecord] = {}
_state_lock = asyncio.Lock()


async def _put_state(state: str, record: _StateRecord) -> None:
    async with _state_lock:
        _gc_expired_locked()
        _state_store[state] = record


async def _take_state(state: str) -> _StateRecord | None:
    """取走(one-shot — 取一次後失效);過期 → None。"""
    async with _state_lock:
        _gc_expired_locked()
        rec = _state_store.pop(state, None)
        if rec is None:
            return None
        if time.time() - rec.created_at > _STATE_TTL_SECONDS:
            return None
        return rec


def _gc_expired_locked() -> None:
    """同步清過期 state(call 時必須持 _state_lock)。"""
    now = time.time()
    expired = [s for s, r in _state_store.items() if now - r.created_at > _STATE_TTL_SECONDS]
    for s in expired:
        _state_store.pop(s, None)


# ─── SecureStorage(module singleton)─────────────────────────────────────────


_storage: SecureStorageBackend | None = None


def _backend() -> SecureStorageBackend:
    global _storage
    if _storage is None:
        _storage = create_backend()
    return _storage


def reset_backend_for_tests(backend: SecureStorageBackend | None) -> None:
    """測試 inject mock backend;傳 None → 下次 lazy create。"""
    global _storage
    _storage = backend


def _token_key(server_name: str, user_id: str) -> str:
    return f"mcp:{server_name}:{user_id}"


# ─── Public flow API ─────────────────────────────────────────────────────────


async def start_web_oauth_flow(
    server_name: str,
    user_id: str,
    *,
    redirect_uri: str,
) -> tuple[str, str]:
    """產 state token + 拼 authorize_url。

    Returns:
        (authorize_url, state)。前端拿 authorize_url 用 window.open 開,user 完成
        授權後第三方會 redirect 回 redirect_uri 帶 ?state=...&code=...

    Raises:
        ValueError: provider 不存在 / env 沒設好。
    """
    provider = get_provider(server_name)
    if provider is None:
        raise ValueError(f"Unknown OAuth provider {server_name!r}")

    state = secrets.token_urlsafe(24)
    await _put_state(
        state,
        _StateRecord(
            server_name=server_name,
            user_id=user_id,
            redirect_uri=redirect_uri,
            created_at=time.time(),
        ),
    )

    if provider.name == "dev-mock":
        # 直接打回 callback 模擬 user 已授權
        params = {"state": state, "code": "dev-mock-code"}
        return f"{redirect_uri}?{urlencode(params)}", state

    if not provider.available():
        raise ValueError(
            f"Provider {server_name!r} is not configured: set "
            f"{provider.client_id_env} and {provider.client_secret_env}.",
        )

    params = {
        "client_id": provider.client_id() or "",
        "redirect_uri": redirect_uri,
        "scope": " ".join(provider.scopes),
        "state": state,
        "response_type": "code",
    }
    return f"{provider.authorize_url}?{urlencode(params)}", state


async def handle_oauth_callback(state: str, code: str) -> str:
    """處理 callback:換 token 後存 SecureStorage。

    Returns:
        server_name(callback handler 用來決定 render 訊息)。

    Raises:
        ValueError: state 不存在 / 過期 / token exchange 失敗。
    """
    rec = await _take_state(state)
    if rec is None:
        raise ValueError("Invalid or expired OAuth state token.")

    provider = get_provider(rec.server_name)
    if provider is None:
        raise ValueError(f"Provider {rec.server_name!r} no longer registered.")

    token_payload: dict[str, Any]
    if provider.name == "dev-mock":
        token_payload = {
            "access_token": f"dev-mock-token-{rec.user_id}",
            "raw": {"note": "synthetic token from dev-mock provider"},
        }
    else:
        token_payload = await _exchange_code(provider, code, rec.redirect_uri)

    await _backend().set(
        _token_key(rec.server_name, rec.user_id),
        json.dumps(token_payload),
    )
    logger.info(
        "oauth_token_stored", extra={"server": rec.server_name, "user_id": rec.user_id},
    )
    return rec.server_name


async def _exchange_code(
    provider: OAuthProvider, code: str, redirect_uri: str,
) -> dict[str, Any]:
    """POST token endpoint。GitHub / Linear 都接受 form body + Accept: json。"""
    data = {
        "client_id": provider.client_id() or "",
        "client_secret": provider.client_secret() or "",
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            provider.token_url,
            data=data,
            headers={"Accept": "application/json"},
        )
    if resp.status_code != 200:
        raise ValueError(
            f"Token exchange for {provider.name} returned "
            f"{resp.status_code}: {resp.text[:200]}",
        )
    body = resp.json()
    if not isinstance(body, dict) or "access_token" not in body:
        raise ValueError(
            f"Token endpoint for {provider.name} did not return access_token; "
            f"got {body!r}",
        )
    return {
        "access_token": body["access_token"],
        "refresh_token": body.get("refresh_token"),
        "expires_at": body.get("expires_in"),
        "raw": body,
    }


async def is_connected(server_name: str, user_id: str) -> bool:
    return await _backend().get(_token_key(server_name, user_id)) is not None


async def disconnect(server_name: str, user_id: str) -> None:
    await _backend().delete(_token_key(server_name, user_id))


# ─── Phase 5 backwards compat ────────────────────────────────────────────────


def start_local_oauth_flow(server_name: str, authorize_url: str) -> str:  # noqa: ARG001
    """本機 callback 流程仍未實作 — CLI 仍走 stdio env 注入。"""
    raise NotImplementedError(
        f"Local OAuth callback for MCP server {server_name!r} not implemented "
        "for CLI mode. Use the web Settings → Connections UI (Phase 25).",
    )
