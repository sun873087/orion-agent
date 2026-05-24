"""LLMProvider Protocol —+ 透過此介面跑 agent loop。

兩個實作:
  - AnthropicProvider:直接呼 Anthropic Messages API HTTP 端點
  - OpenAIProvider:直接呼 OpenAI Responses API HTTP 端點

兩家都用各自的 Python 套件(`anthropic` / `openai`),這些是薄 HTTP wrapper,
不是 agent 框架。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol

from orion_model.events import NormalizedEvent
from orion_model.tool_def import ToolDefinition
from orion_model.types import NormalizedMessage


@dataclass
class ProviderCapabilities:
    """Provider 支援哪些 feature。/ 6 / 9 等用 capability flag 條件處理。"""

    prompt_caching: bool # 手動 cache_control(Anthropic)
    auto_caching: bool # 自動 caching(OpenAI prefix > 1024 tokens)
    parallel_tool_calls: bool
    native_mcp: bool
    structured_output: bool # response_format json_schema
    reasoning_blocks: bool # extended thinking / o-series reasoning
    max_context_tokens: int


ReasoningEffort = Literal["minimal", "low", "medium", "high"]


class LLMProvider(Protocol):
    """LLM Provider 介面。"""

    name: str # "anthropic" / "openai"
    model: str
    capabilities: ProviderCapabilities

    def stream(
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
        """主要呼叫。yield normalized events。

        Args:
            system: 系統 prompt。str 或 list[str](list 模式 Anthropic 會在最後加
                cache_control,OpenAI 直接 concat 成單字串)。
            messages: 訊息歷史(normalized 格式)。
            tools: 工具定義(可選)。
            max_tokens: 最大輸出 token。
            temperature: 取樣溫度(可選)。
            cache_breakpoints: messages indices 標 cache 切點(Anthropic only,
                OpenAI 自動 cache 忽略此參數)。
            reasoning_effort: 推理深度(僅支援 reasoning_blocks 的模型有效)。

        Yields:
            NormalizedEvent —+ 處理這些事件。
        """
        ...

    def estimate_cost(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
        reasoning_tokens: int = 0,
    ) -> float:
        """估算這次呼叫成本(USD)。"""
        ...


_TEST_PROVIDER_FACTORY: "callable | None" = None


def set_test_provider_factory(factory: "callable | None") -> None:
    """E e2e:測試環境注入 fake provider。

    使用方式(只在 test fixture 用,production 永遠 None):
        from orion_sdk._testing import MockProvider
        set_test_provider_factory(lambda name, model: MockProvider(...))

    呼叫 `set_test_provider_factory(None)` 清除。
    """
    global _TEST_PROVIDER_FACTORY
    _TEST_PROVIDER_FACTORY = factory


def get_provider(provider_name: str, model: str) -> LLMProvider:
    """工廠函式。

    Args:
        provider_name: "anthropic" / "openai" / "ollama"
        model: 模型 ID(e.g. "claude-sonnet-4-6", "gpt-5")

    Returns:
        對應的 LLMProvider 實例。

    優先順序:
        1. `set_test_provider_factory()` 設定(e2e)→ 回 fake
        2. 否則回對應 provider(Anthropic / OpenAI / Ollama)

    `ORION_MODEL_PROXY_URL` env有設時,各 provider 的 base_url
    自動換成 `{proxy}/openai` 或 `{proxy}/anthropic` — proxy 是 transparent
    reverse proxy,SDK 自己跟 proxy 講原生 wire format,**這個 factory 不必
    管 proxy 細節**。Ollama 本機 daemon,不經 proxy。
    """
    if _TEST_PROVIDER_FACTORY is not None:
        return _TEST_PROVIDER_FACTORY(provider_name, model)
    if provider_name == "anthropic":
        from orion_model.anthropic_provider import AnthropicProvider

        return AnthropicProvider(model=model)
    if provider_name == "openai":
        from orion_model.openai_provider import OpenAIProvider

        return OpenAIProvider(model=model)
    if provider_name == "ollama":
        from orion_model.ollama_provider import OllamaProvider

        return OllamaProvider(model=model)
    if provider_name == "openrouter":
        from orion_model.openrouter_provider import OpenRouterProvider

        return OpenRouterProvider(model=model)
    raise ValueError(f"Unknown provider: {provider_name!r}")
