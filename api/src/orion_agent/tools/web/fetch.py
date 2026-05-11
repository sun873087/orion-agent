"""WebFetchTool — fetch a URL,strip HTML 成 plain text。

對應 TS Claude Code `src/tools/WebFetchTool/`。Phase 1 簡化版:
- httpx 抓 URL
- BeautifulSoup4 移 script/style/nav/header/footer/aside
- 取剩下文字,壓多餘空白
- 30 秒 timeout、200KB 上限

Phase 1 故意不做的:
- readability 抽精華(spec 提了但有 timeout/error 風險,延後)
- JS 渲染(headless browser,Phase 後段或不做)
- robots.txt 檢查
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator

import httpx
from bs4 import BeautifulSoup, Tag
from pydantic import Field

from orion_agent.core.abort import abort_aware_scope
from orion_agent.core.state import AgentContext
from orion_agent.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput
from orion_agent.storage.url_cache import get_or_create_url_cache

_TIMEOUT_S = 30
_MAX_BYTES = 200 * 1024
_MAX_OUTPUT_CHARS = 50_000

_STRIP_TAGS = ("script", "style", "nav", "header", "footer", "aside", "form", "noscript")


class WebFetchInput(ToolInput):
    """WebFetchTool 的 input schema。"""

    url: str = Field(..., description="HTTP/HTTPS URL to fetch.")


class WebFetchTool:
    name = "WebFetch"
    description = (
        "Fetch a URL and return its main text content (HTML stripped). "
        "30s timeout, 200KB body limit, output truncated past ~50KB."
    )
    input_schema = WebFetchInput

    async def call(
        self,
        input: WebFetchInput,
        ctx: AgentContext,
    ) -> AsyncIterator[ToolEvent]:
        url = input.url.strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            yield ErrorEvent(message=f"URL must start with http:// or https://: {url!r}")
            return

        # Phase 18:per-session URL cache(TTL 預設 5 min)。同 URL 在同 session
        # 內重複 fetch 走 cache,標 `[cached]` 給模型看。
        cache = get_or_create_url_cache(ctx)
        hit = cache.get(url)
        if hit is not None:
            for ev in self._render(url, hit.body, hit.content_type, cached=True):
                yield ev
            return

        # Phase 16:abort_aware_scope 讓 ctx.abort_event 中途 set 時即刻關 httpx 連線
        resp: httpx.Response | None = None
        try:
            async with abort_aware_scope(ctx.abort_event) as abort_scope:
                async with httpx.AsyncClient(
                    timeout=_TIMEOUT_S,
                    follow_redirects=True,
                    headers={"User-Agent": "orion-agent/0.1 (+https://github.com)"},
                ) as client:
                    resp = await client.get(url)
        except httpx.TimeoutException:
            yield ErrorEvent(message=f"timeout fetching {url}")
            return
        except httpx.RequestError as e:
            yield ErrorEvent(message=f"fetch failed: {type(e).__name__}: {e}")
            return

        if abort_scope.cancel_called or resp is None:
            yield ErrorEvent(message=f"aborted fetching {url}")
            return

        if resp.status_code >= 400:
            yield ErrorEvent(
                message=f"HTTP {resp.status_code} from {url}: {resp.reason_phrase}"
            )
            return

        content_type = resp.headers.get("content-type", "").lower()
        body = resp.content[:_MAX_BYTES]
        cache.put(url, body, content_type)

        for ev in self._render(url, body, content_type, cached=False):
            yield ev

    def _render(
        self,
        url: str,
        body: bytes,
        content_type: str,
        *,
        cached: bool,
    ) -> list[ToolEvent]:
        """把 raw body 處理成給模型看的 TextEvent / ErrorEvent。"""
        marker = " [cached]" if cached else ""

        # 純文字 / JSON 直接回
        if "text/html" not in content_type and "<html" not in body[:500].decode(
            "utf-8", errors="ignore"
        ).lower():
            try:
                text = body.decode("utf-8", errors="replace")
            except Exception as e:  # noqa: BLE001
                return [ErrorEvent(message=f"could not decode body: {e}")]
            return [
                TextEvent(
                    text=self._truncate(
                        f"# {url}{marker}\n[type: {content_type}]\n\n{text}"
                    )
                )
            ]

        # HTML → 清乾淨
        try:
            soup = BeautifulSoup(body, "html.parser")
            for tag_name in _STRIP_TAGS:
                for tag_el in soup.find_all(tag_name):
                    if isinstance(tag_el, Tag):
                        tag_el.decompose()

            title_tag = soup.find("title")
            title = (
                title_tag.get_text(strip=True)
                if isinstance(title_tag, Tag)
                else "(no title)"
            )
            text = soup.get_text(separator="\n", strip=True)
            text = re.sub(r"\n{3,}", "\n\n", text)
        except Exception as e:  # noqa: BLE001
            return [ErrorEvent(message=f"HTML parse failed: {type(e).__name__}: {e}")]

        out = f"# {title}{marker}\nURL: {url}\n\n{text}"
        return [TextEvent(text=self._truncate(out))]

    @staticmethod
    def _truncate(s: str) -> str:
        if len(s) <= _MAX_OUTPUT_CHARS:
            return s
        return s[:_MAX_OUTPUT_CHARS] + f"\n... [+{len(s) - _MAX_OUTPUT_CHARS} chars truncated]"

    def is_concurrency_safe(self, input: WebFetchInput) -> bool:  # noqa: ARG002
        return True  # 純讀(沒有 mutate 本機 state)

    def is_read_only(self, input: WebFetchInput) -> bool:  # noqa: ARG002
        return True

    def max_result_size_chars(self) -> int | float:
        return _MAX_OUTPUT_CHARS
