"""HTTP proxy provider — Phase 31-X。

`get_provider()` 偵測 `ORION_MODEL_PROXY_URL` env 時走這條路徑而不是直接呼
Anthropic / OpenAI / Ollama HTTP。Proxy 負責真實 provider 連線、key 管理、
cost 統計、routing,host 端只需要 NormalizedMessage / NormalizedEvent。

Wire format(Orion-native):
    POST {base_url}/v1/messages
    Headers: Authorization: Bearer {ORION_MODEL_PROXY_KEY}(optional)
    Body: {
        "provider": "anthropic|openai|ollama",
        "model": "claude-sonnet-4-6",
        "system": "..." | ["..."],
        "messages": [NormalizedMessage, ...],
        "tools": [ToolDefinition, ...] | null,
        "max_tokens": 4096,
        "temperature": 0.7 | null,
        "cache_breakpoints": [int, ...] | null,
        "reasoning_effort": "low|medium|high|minimal" | null,
    }
    Response: NDJSON streaming(每行 1 個 NormalizedEvent JSON,Content-Type
              application/x-ndjson),最後一行 message_stop。

Capabilities + estimate_cost 用本地 catalog / pricing,**proxy 不必回答**。
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx
from pydantic import TypeAdapter

from orion_model.catalog import get_max_context_tokens, get_supports_reasoning
from orion_model.events import NormalizedEvent
from orion_model.provider import ProviderCapabilities, ReasoningEffort
from orion_model.tool_def import ToolDefinition
from orion_model.types import NormalizedMessage


# 對應 target provider 的 capability profile — proxy 把哪個 backend 接下去
# 由 wire-layer 帶 provider 字段決定,capability flag host 端先猜對應 backend
# 的常見能力。實際 provider 不支援的請求(例如 anthropic 沒 structured_output)
# 會在 proxy 那邊回 error,host code 不必動。
_PROVIDER_CAPABILITY_PROFILE: dict[str, dict[str, Any]] = {
    "anthropic": {
        "prompt_caching": True,
        "auto_caching": False,
        "parallel_tool_calls": True,
        "native_mcp": True,
        "structured_output": False,
    },
    "openai": {
        "prompt_caching": False,
        "auto_caching": True,
        "parallel_tool_calls": True,
        "native_mcp": False,
        "structured_output": True,
    },
    "ollama": {
        "prompt_caching": False,
        "auto_caching": False,
        "parallel_tool_calls": True,
        "native_mcp": False,
        "structured_output": False,
    },
}

_DEFAULT_CONTEXT_TOKENS = 200_000

# pydantic TypeAdapter 用來解析 NDJSON 每行回對應 event 子類型
_event_adapter: TypeAdapter[NormalizedEvent] = TypeAdapter(NormalizedEvent)


def _proxy_url() -> str | None:
    """讀 env;沒設回 None。"""
    url = os.environ.get("ORION_MODEL_PROXY_URL")
    if not url:
        return None
    return url.rstrip("/")


def _proxy_key() -> str | None:
    return os.environ.get("ORION_MODEL_PROXY_KEY")


class HttpProxyProvider:
    """LLMProvider 實作 — 把 stream() 經 HTTP 轉發給 Orion Model Proxy。

    Host code 不需要知道 proxy 存在;`get_provider()` 工廠根據 env 自動切換。
    Streaming 時 SSE 替代 NDJSON(實作簡單,每行就是一個 event JSON)。
    """

    capabilities: ProviderCapabilities

    def __init__(
        self,
        *,
        provider_name: str,
        model: str,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 600.0,
    ) -> None:
        self.name = provider_name
        self.model = model
        self._base_url = (base_url or _proxy_url() or "").rstrip("/")
        if not self._base_url:
            raise ValueError(
                "ORION_MODEL_PROXY_URL not set — refusing to construct HttpProxyProvider"
            )
        self._api_key = api_key or _proxy_key()
        self._timeout = timeout

        profile = _PROVIDER_CAPABILITY_PROFILE.get(provider_name) or {}
        self.capabilities = ProviderCapabilities(
            prompt_caching=profile.get("prompt_caching", False),
            auto_caching=profile.get("auto_caching", False),
            parallel_tool_calls=profile.get("parallel_tool_calls", True),
            native_mcp=profile.get("native_mcp", False),
            structured_output=profile.get("structured_output", False),
            reasoning_blocks=get_supports_reasoning(provider_name, model),
            max_context_tokens=get_max_context_tokens(provider_name, model)
            or _DEFAULT_CONTEXT_TOKENS,
        )

    async def stream(
        self,
        *,
        system: str | list[str],
        messages: list[NormalizedMessage],
        tools: list[ToolDefinition] | None = None,
        max_tokens: int = 4096,
        temperature: float | None = None,
        cache_breakpoints: list[int] | None = None,
        reasoning_effort: ReasoningEffort | None = None,
    ) -> AsyncIterator[NormalizedEvent]:
        payload: dict[str, Any] = {
            "provider": self.name,
            "model": self.model,
            "system": system,
            "messages": [m.model_dump(mode="json") for m in messages],
            "tools": (
                [t.model_dump(mode="json") for t in tools] if tools else None
            ),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "cache_breakpoints": cache_breakpoints,
            "reasoning_effort": reasoning_effort,
        }
        headers = {"Content-Type": "application/json", "Accept": "application/x-ndjson"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream(
                "POST",
                f"{self._base_url}/v1/messages",
                json=payload,
                headers=headers,
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    text = body.decode("utf-8", errors="replace")[:500]
                    raise RuntimeError(
                        f"orion-model-proxy returned {resp.status_code}: {text}"
                    )
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        # Proxy 不該送非 JSON line;safety net
                        continue
                    # Proxy 可能 emit 自家 error frame(非 NormalizedEvent)
                    if isinstance(data, dict) and data.get("type") == "error":
                        msg = data.get("message", "unknown proxy error")
                        raise RuntimeError(f"proxy error: {msg}")
                    yield _event_adapter.validate_python(data)

    def estimate_cost(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
        reasoning_tokens: int = 0,
    ) -> float:
        """走 host 本地 catalog 算成本 — proxy 那邊也會算一份(認帳的那份),
        host 端這個只是給 conversation.stats 顯給 user 看。同一份 pricing.json
        所以結果一致。"""
        from orion_model.pricing import get_pricing

        p = get_pricing(self.name, self.model)
        # OpenAI 把 reasoning_tokens 算在 output_tokens 裡 — 跟 OpenAIProvider 對齊
        return round(
            (
                input_tokens * p.get("input", 0.0)
                + (output_tokens + reasoning_tokens) * p.get("output", 0.0)
                + cache_read_tokens * p.get("cache_read", p.get("input", 0.0))
                + cache_creation_tokens
                * p.get("cache_creation", p.get("input", 0.0))
            )
            / 1_000_000,
            6,
        )


__all__ = ["HttpProxyProvider", "_proxy_url", "_proxy_key"]
