"""Phase 18:WebFetchTool URL cache 行為。

- 第二次 fetch 同 URL 不打網(httpx call_count 驗證)
- TTL 過期後重新打網
- 不同 URL 各自獨立
- 跨 AgentContext 不共享(per-session)
- LRU 超 max_entries 自動 evict
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import pytest

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import TextEvent
from orion_sdk.storage.url_cache import UrlCache, get_or_create_url_cache
from orion_sdk.tools.web.fetch import WebFetchInput, WebFetchTool


def _mock_httpx(monkeypatch: pytest.MonkeyPatch, handler: Any) -> dict[str, int]:
    """裝 httpx mock transport,回傳一個 counter dict 讓測試 assert 呼叫次數。"""
    counter = {"n": 0}

    def wrapped(request: httpx.Request) -> httpx.Response:
        counter["n"] += 1
        return handler(request)

    transport = httpx.MockTransport(wrapped)
    real_client = httpx.AsyncClient

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return counter


def _ok_html(_: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        text="<html><head><title>T</title></head><body>hello orion</body></html>",
        headers={"content-type": "text/html; charset=utf-8"},
    )


@pytest.mark.asyncio
async def test_second_fetch_does_not_hit_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter = _mock_httpx(monkeypatch, _ok_html)
    tool = WebFetchTool()
    ctx = AgentContext()

    r1 = [
        e async for e in tool.call(WebFetchInput(url="https://x/"), ctx)
    ]
    r2 = [
        e async for e in tool.call(WebFetchInput(url="https://x/"), ctx)
    ]

    assert counter["n"] == 1
    assert isinstance(r1[0], TextEvent)
    assert isinstance(r2[0], TextEvent)
    assert "[cached]" not in r1[0].text
    assert "[cached]" in r2[0].text


@pytest.mark.asyncio
async def test_different_urls_each_hit_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter = _mock_httpx(monkeypatch, _ok_html)
    tool = WebFetchTool()
    ctx = AgentContext()

    [e async for e in tool.call(WebFetchInput(url="https://a/"), ctx)]
    [e async for e in tool.call(WebFetchInput(url="https://b/"), ctx)]
    [e async for e in tool.call(WebFetchInput(url="https://a/"), ctx)]  # cached

    assert counter["n"] == 2


@pytest.mark.asyncio
async def test_cache_is_per_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter = _mock_httpx(monkeypatch, _ok_html)
    tool = WebFetchTool()
    ctx_a = AgentContext()
    ctx_b = AgentContext()

    [e async for e in tool.call(WebFetchInput(url="https://x/"), ctx_a)]
    [e async for e in tool.call(WebFetchInput(url="https://x/"), ctx_b)]

    # 不同 session 各自 fetch
    assert counter["n"] == 2


@pytest.mark.asyncio
async def test_ttl_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TTL 過期 → cache miss 重打網。用 monotonic monkeypatch 跳時間。"""
    counter = _mock_httpx(monkeypatch, _ok_html)
    tool = WebFetchTool()
    ctx = AgentContext()
    # 預先建 cache 限定短 TTL(避免依賴 env)
    ctx.url_cache = UrlCache(ttl_seconds=0.5)

    [e async for e in tool.call(WebFetchInput(url="https://x/"), ctx)]
    # 推進 monotonic 超過 ttl
    base = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: base + 10.0)
    [e async for e in tool.call(WebFetchInput(url="https://x/"), ctx)]

    assert counter["n"] == 2


def test_lru_eviction() -> None:
    """超 max_entries 後最舊 entry 被踢。"""
    cache = UrlCache(ttl_seconds=300, max_entries=3)
    cache.put("a", b"A", "text/plain")
    cache.put("b", b"B", "text/plain")
    cache.put("c", b"C", "text/plain")
    assert len(cache) == 3
    cache.put("d", b"D", "text/plain")  # 應 evict a
    assert len(cache) == 3
    assert cache.get("a") is None
    assert cache.get("d") is not None


def test_lru_recency_on_get() -> None:
    """get 命中 → bump to MRU,避免被 evict。"""
    cache = UrlCache(ttl_seconds=300, max_entries=3)
    cache.put("a", b"A", "text/plain")
    cache.put("b", b"B", "text/plain")
    cache.put("c", b"C", "text/plain")
    # 把 'a' 訪問成 MRU
    cache.get("a")
    cache.put("d", b"D", "text/plain")  # 應 evict 'b'(最舊)
    assert cache.get("b") is None
    assert cache.get("a") is not None


def test_ttl_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORION_WEBFETCH_TTL_SECONDS", "42")
    cache = UrlCache()
    assert cache.ttl_seconds == 42.0


def test_ttl_env_invalid_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORION_WEBFETCH_TTL_SECONDS", "not-a-number")
    cache = UrlCache()
    assert cache.ttl_seconds == 300.0


def test_get_or_create_idempotent() -> None:
    """同一 ctx 多次 get_or_create_url_cache 應回同一物件。"""
    ctx = AgentContext()
    a = get_or_create_url_cache(ctx)
    b = get_or_create_url_cache(ctx)
    assert a is b
