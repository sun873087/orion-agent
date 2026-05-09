"""WebSearchTool — Google search via SerpAPI.

API key from `SERPAPI_API_KEY` env (read at call time so monkeypatching works in
tests). When the env var is missing the tool returns a clear error rather than
crashing — model can fall back to WebFetch on a known URL.

Why SerpAPI rather than direct Google: SerpAPI handles rate limits, IP blocks,
and result parsing. Direct scraping needs a headless browser and a proxy pool.

Result format: markdown with ranked list of (title, URL, snippet). Stable enough
for the model to chain WebFetch on individual links.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import httpx
from pydantic import Field

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput

_TIMEOUT_S = 30
_MAX_OUTPUT_CHARS = 50_000
_SERPAPI_URL = "https://serpapi.com/search.json"


class WebSearchInput(ToolInput):
    query: str = Field(..., description="Search query string.")
    num_results: int = Field(
        10,
        ge=1,
        le=20,
        description="Number of organic results to return (1-20, default 10).",
    )


class WebSearchTool:
    name = "WebSearch"
    description = (
        "Search the web via SerpAPI (Google engine). Returns a ranked list of "
        "results with title, URL, and snippet. Requires SERPAPI_API_KEY env var. "
        "Pair with WebFetch to read full content of a returned URL."
    )
    input_schema = WebSearchInput

    async def call(
        self,
        input: WebSearchInput,
        ctx: AgentContext,  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        api_key = os.environ.get("SERPAPI_API_KEY")
        if not api_key:
            yield ErrorEvent(
                message=(
                    "WebSearch unavailable: SERPAPI_API_KEY env var is not set. "
                    "Get a key at https://serpapi.com/manage-api-key and add it "
                    "to api/.env."
                ),
            )
            return

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
                resp = await client.get(
                    _SERPAPI_URL,
                    params={
                        "q": input.query,
                        "api_key": api_key,
                        "engine": "google",
                        "num": input.num_results,
                    },
                )
        except httpx.TimeoutException:
            yield ErrorEvent(message=f"WebSearch timeout for query {input.query!r}")
            return
        except httpx.RequestError as e:
            yield ErrorEvent(
                message=f"WebSearch network error: {type(e).__name__}: {e}",
            )
            return

        if resp.status_code >= 400:
            body = resp.text[:200]
            yield ErrorEvent(
                message=f"SerpAPI HTTP {resp.status_code}: {body}",
            )
            return

        try:
            data = resp.json()
        except ValueError as e:
            yield ErrorEvent(message=f"SerpAPI returned non-JSON: {e}")
            return

        if isinstance(data, dict) and "error" in data:
            yield ErrorEvent(message=f"SerpAPI error: {data['error']}")
            return

        results = data.get("organic_results") if isinstance(data, dict) else None
        if not isinstance(results, list) or not results:
            yield TextEvent(text=f'No search results for "{input.query}".')
            return

        lines = [f'# Search results for "{input.query}"', ""]
        for r in results[: input.num_results]:
            if not isinstance(r, dict):
                continue
            title = r.get("title", "(no title)")
            link = r.get("link", "")
            snippet = r.get("snippet", "")
            lines.append(f"## {title}")
            if link:
                lines.append(f"<{link}>")
            if snippet:
                lines.append(snippet)
            lines.append("")

        out = "\n".join(lines).rstrip()
        yield TextEvent(text=self._truncate(out))

    @staticmethod
    def _truncate(s: str) -> str:
        if len(s) <= _MAX_OUTPUT_CHARS:
            return s
        return s[:_MAX_OUTPUT_CHARS] + f"\n... [+{len(s) - _MAX_OUTPUT_CHARS} chars truncated]"

    def is_concurrency_safe(self, input: WebSearchInput) -> bool:  # noqa: ARG002
        return True

    def is_read_only(self, input: WebSearchInput) -> bool:  # noqa: ARG002
        return True

    def max_result_size_chars(self) -> int | float:
        return _MAX_OUTPUT_CHARS
