"""WebSearchTool — httpx mock transport, no real network."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import ErrorEvent, TextEvent
from orion_agent.tools.web.search import WebSearchInput, WebSearchTool


def _mock_httpx(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_no_api_key_returns_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    tool = WebSearchTool()
    events = [
        e
        async for e in tool.call(
            WebSearchInput(query="anything"), AgentContext(),
        )
    ]
    assert len(events) == 1
    assert isinstance(events[0], ErrorEvent)
    assert "SERPAPI_API_KEY" in events[0].message


@pytest.mark.asyncio
async def test_returns_results_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERPAPI_API_KEY", "fake-key")

    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "organic_results": [
                    {
                        "title": "Anthropic Claude",
                        "link": "https://anthropic.com/claude",
                        "snippet": "Frontier AI assistant.",
                    },
                    {
                        "title": "OpenAI",
                        "link": "https://openai.com",
                        "snippet": "Builders of GPT.",
                    },
                ],
            },
        )

    _mock_httpx(monkeypatch, handler)

    tool = WebSearchTool()
    events = [
        e
        async for e in tool.call(
            WebSearchInput(query="frontier llms"), AgentContext(),
        )
    ]

    assert len(events) == 1 and isinstance(events[0], TextEvent)
    out = events[0].text
    assert "frontier llms" in out
    assert "Anthropic Claude" in out
    assert "https://anthropic.com/claude" in out
    assert "Frontier AI assistant." in out
    assert "OpenAI" in out
    # Confirm we hit SerpAPI with the right query + key
    assert "serpapi.com/search.json" in captured["url"]
    assert "q=frontier+llms" in captured["url"]
    assert "api_key=fake-key" in captured["url"]


@pytest.mark.asyncio
async def test_serpapi_error_field_surfaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SERPAPI_API_KEY", "fake-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "Invalid API key"})

    _mock_httpx(monkeypatch, handler)
    tool = WebSearchTool()
    events = [
        e
        async for e in tool.call(WebSearchInput(query="x"), AgentContext())
    ]
    assert isinstance(events[0], ErrorEvent)
    assert "Invalid API key" in events[0].message


@pytest.mark.asyncio
async def test_http_error_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERPAPI_API_KEY", "fake-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limited")

    _mock_httpx(monkeypatch, handler)
    tool = WebSearchTool()
    events = [
        e
        async for e in tool.call(WebSearchInput(query="x"), AgentContext())
    ]
    assert isinstance(events[0], ErrorEvent)
    assert "429" in events[0].message


@pytest.mark.asyncio
async def test_empty_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERPAPI_API_KEY", "fake-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"organic_results": []})

    _mock_httpx(monkeypatch, handler)
    tool = WebSearchTool()
    events = [
        e
        async for e in tool.call(
            WebSearchInput(query="something obscure"), AgentContext(),
        )
    ]
    assert isinstance(events[0], TextEvent)
    assert "No search results" in events[0].text


@pytest.mark.asyncio
async def test_non_json_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERPAPI_API_KEY", "fake-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    _mock_httpx(monkeypatch, handler)
    tool = WebSearchTool()
    events = [
        e
        async for e in tool.call(WebSearchInput(query="x"), AgentContext())
    ]
    assert isinstance(events[0], ErrorEvent)


@pytest.mark.asyncio
async def test_input_validation_clamps_num_results() -> None:
    # pydantic should reject num_results > 20
    with pytest.raises(Exception):  # noqa: PT011, BLE001
        WebSearchInput(query="x", num_results=99)


# json import only here to silence unused-import warning if test_returns... is skipped
_ = json
