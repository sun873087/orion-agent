"""WebFetchTool — 用 httpx mock transport 測,不打真實網路。"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent
from orion_sdk.tools.web.fetch import WebFetchInput, WebFetchTool


@pytest.mark.asyncio
async def test_fetch_html(monkeypatch: pytest.MonkeyPatch) -> None:
    html = """
    <html><head><title>Test Page</title></head>
    <body>
      <nav>menu</nav>
      <main><h1>Real Content</h1><p>Hello orion.</p></main>
      <script>console.log('x')</script>
      <footer>foot</footer>
    </body></html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=html,
            headers={"content-type": "text/html; charset=utf-8"},
        )

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def mock_client_factory(**kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", mock_client_factory)

    tool = WebFetchTool()
    events = [
        e
        async for e in tool.call(
            WebFetchInput(url="https://example.com/"), AgentContext()
        )
    ]

    assert isinstance(events[0], TextEvent)
    text = events[0].text
    assert "Test Page" in text
    assert "Real Content" in text
    assert "Hello orion" in text
    # nav / script / footer 應已被 strip
    assert "menu" not in text
    assert "console.log" not in text
    assert "foot" not in text


@pytest.mark.asyncio
async def test_invalid_scheme_rejected() -> None:
    tool = WebFetchTool()
    events = [
        e
        async for e in tool.call(
            WebFetchInput(url="ftp://example.com/"), AgentContext()
        )
    ]
    assert isinstance(events[0], ErrorEvent)


@pytest.mark.asyncio
async def test_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)

    tool = WebFetchTool()
    events = [
        e
        async for e in tool.call(
            WebFetchInput(url="https://example.com/missing"), AgentContext()
        )
    ]
    assert isinstance(events[0], ErrorEvent)
    assert "404" in events[0].message
