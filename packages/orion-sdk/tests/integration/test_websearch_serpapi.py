"""Real SerpAPI WebSearch — needs SERPAPI_API_KEY。

Verifies WebSearch tool actually hits SerpAPI and parses results.
"""

from __future__ import annotations

import os

import pytest

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent
from orion_sdk.tools.web.search import WebSearchInput, WebSearchTool

pytestmark = pytest.mark.skipif(
    not os.environ.get("SERPAPI_API_KEY"),
    reason="SERPAPI_API_KEY not set",
)


@pytest.mark.asyncio
async def test_websearch_returns_results() -> None:
    tool = WebSearchTool()
    ctx = AgentContext()
    events = []
    async for ev in tool.call(WebSearchInput(query="python asyncio docs", num_results=3), ctx):
        events.append(ev)

    text_events = [e for e in events if isinstance(e, TextEvent)]
    errors = [e for e in events if isinstance(e, ErrorEvent)]
    assert not errors, f"got errors: {[e.message for e in errors]}"
    assert text_events, "no TextEvent emitted"
    combined = "\n".join(e.text for e in text_events)
    assert "python" in combined.lower()
    # 至少有 url 出現(每筆 result 都帶 URL)
    assert "http" in combined.lower()
