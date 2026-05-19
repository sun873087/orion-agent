"""Anthropic provider — 直接呼 Anthropic Messages API HTTP 端點。

不用 Anthropic Agent SDK,只用 anthropic 套件(薄 HTTP wrapper)。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, cast

from anthropic import AsyncAnthropic

from orion_model.cache_config import (
    CacheTTLConfig,
    build_cache_control,
    load_cache_ttl_config,
)
from orion_model.catalog import (
    get_max_context_tokens,
    get_supports_reasoning,
)
from orion_model.events import (
    MessageStartEvent,
    MessageStopEvent,
    NormalizedEvent,
    NormalizedUsage,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ToolUseInputDeltaEvent,
    ToolUseStartEvent,
    ToolUseStopEvent,
)
from orion_model.pricing import get_pricing
from orion_model.provider import ProviderCapabilities, ReasoningEffort
from orion_model.tool_def import ToolDefinition
from orion_model.translation.anthropic import (
    apply_cache_breakpoints,
    translate_messages_to_anthropic,
    translate_tools_to_anthropic,
)
from orion_model.types import NormalizedMessage

_DEFAULT_CONTEXT_TOKENS = 200_000

_REASONING_BUDGET = {
    "minimal": 1024,
    "low": 4096,
    "medium": 16384,
    "high": 32768,
}


def _build_system_param(
    system: str | list[str],
    ttl_config: CacheTTLConfig | None = None,
) -> str | list[dict[str, Any]]:
    """str → 直傳;list[str] → 每段都標 cache_control(Anthropic 限 4 個 bp)。

    慣例:caller 保證 list 內每段都是 cacheable(session-stable 或更穩定)。
    volatile per-turn 內容應由 caller 注入 user message,不放在 system list。

    TTL 對應:
    - block[0]:static TTL(預設 1h,跨 session 不變)
    - block[1+]:session TTL(預設 1h,session-stable)
    空字串段跳過 cache_control(API 拒收)。
    """
    if isinstance(system, str):
        return system
    cfg = ttl_config or load_cache_ttl_config()
    blocks: list[dict[str, Any]] = []
    for i, s in enumerate(system):
        block: dict[str, Any] = {"type": "text", "text": s}
        if s.strip():
            ttl = cfg.static if i == 0 else cfg.session
            block["cache_control"] = build_cache_control(ttl)
        blocks.append(block)
    return blocks


class AnthropicProvider:
    """直接呼 Claude Messages API。"""

    name = "anthropic"

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        client: AsyncAnthropic | None = None,
    ) -> None:
        self.model = model
        # Phase 31-X — ORION_MODEL_PROXY_URL 有設就把 SDK 的 base_url 指到 proxy
        # /anthropic;沒設走 Anthropic 預設 https://api.anthropic.com。
        # 整個透傳邏輯由 anthropic SDK 自己處理(它本來就支援 base_url),
        # proxy 對它而言是 transparent reverse proxy。
        if client is None:
            import os as _os
            proxy = _os.environ.get("ORION_MODEL_PROXY_URL")
            if proxy:
                # SDK init 階段 strict 要求 api_key 不為 None,proxy 那邊才有
                # 真 key,host 端塞 placeholder 騙過 SDK。proxy reverse 那層
                # 會用真實 ANTHROPIC_API_KEY 覆寫 x-api-key header。
                client = AsyncAnthropic(
                    base_url=f"{proxy.rstrip('/')}/anthropic",
                    api_key=_os.environ.get("ANTHROPIC_API_KEY") or "via-proxy",
                )
            else:
                client = AsyncAnthropic()
        self.client = client
        self.capabilities = ProviderCapabilities(
            prompt_caching=True,
            auto_caching=False,
            parallel_tool_calls=True,
            native_mcp=True,
            structured_output=False,
            reasoning_blocks=get_supports_reasoning(self.name, model),
            max_context_tokens=get_max_context_tokens(self.name, model)
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
        """yield NormalizedEvent。

        Phase 16:`async with client.messages.stream(...)` 是 SDK 提供的 context manager,
        當外圍 cancel scope 觸發 CancelledError,__aexit__ 會關閉 httpx connection。
        因此中途 abort 不需要這層自己處理,直接讓 cancellation propagate 上去即可。
        """
        anthropic_messages = translate_messages_to_anthropic(messages)
        anthropic_tools = translate_tools_to_anthropic(tools or [])

        ttl_cfg = load_cache_ttl_config()

        # System prompt:str 或 list[str](cache_control 邏輯見 _build_system_param)
        system_param = _build_system_param(system, ttl_cfg)

        if cache_breakpoints:
            anthropic_messages = apply_cache_breakpoints(
                anthropic_messages,
                cache_breakpoints,
                cache_control=build_cache_control(ttl_cfg.messages),
            )

        # 額外 kwargs(temperature / thinking)
        extra: dict[str, Any] = {}
        if temperature is not None:
            extra["temperature"] = temperature
        if self.capabilities.reasoning_blocks and reasoning_effort:
            extra["thinking"] = {
                "type": "enabled",
                "budget_tokens": _REASONING_BUDGET[reasoning_effort],
            }

        # 直接呼 Anthropic API HTTP 端點
        async with self.client.messages.stream(
            model=self.model,
            system=system_param,  # type: ignore[arg-type]
            messages=cast(Any, anthropic_messages),
            tools=cast(Any, anthropic_tools) if anthropic_tools else cast(Any, []),
            max_tokens=max_tokens,
            **extra,
        ) as stream:
            current_block_idx: int | None = None
            current_tool_id: str | None = None
            current_tool_name: str | None = None
            current_partial_json = ""

            async for raw_event in stream:
                # SDK streaming events 是 union type;mypy strict 無法 narrow
                # string discriminator,所以邊界視為 Any。emit 出去的
                # NormalizedEvent 仍會被 strict 檢查。
                event: Any = raw_event
                etype: str = event.type

                if etype == "message_start":
                    yield MessageStartEvent(
                        message_id=event.message.id,
                        model=event.message.model,
                    )

                elif etype == "content_block_start":
                    cb = event.content_block
                    current_block_idx = event.index
                    if cb.type == "tool_use":
                        current_tool_id = cb.id
                        current_tool_name = cb.name
                        current_partial_json = ""
                        yield ToolUseStartEvent(
                            block_index=current_block_idx,
                            tool_use_id=current_tool_id,
                            tool_name=current_tool_name,
                        )

                elif etype == "content_block_delta":
                    delta = event.delta
                    delta_type = delta.type
                    if delta_type == "text_delta":
                        yield TextDeltaEvent(text=delta.text)
                    elif delta_type == "thinking_delta":
                        yield ThinkingDeltaEvent(text=delta.thinking)
                    elif delta_type == "input_json_delta":
                        current_partial_json += delta.partial_json
                        yield ToolUseInputDeltaEvent(
                            block_index=current_block_idx or 0,
                            partial_json=delta.partial_json,
                        )

                elif etype == "content_block_stop":
                    if current_tool_id is not None and current_tool_name is not None:
                        try:
                            full_input = (
                                json.loads(current_partial_json) if current_partial_json else {}
                            )
                        except json.JSONDecodeError:
                            full_input = {"_parse_error": current_partial_json}
                        yield ToolUseStopEvent(
                            block_index=current_block_idx or 0,
                            tool_use_id=current_tool_id,
                            tool_name=current_tool_name,
                            full_input=full_input,
                        )
                        current_tool_id = None
                        current_tool_name = None

                elif etype == "message_stop":
                    final = await stream.get_final_message()
                    yield MessageStopEvent(
                        stop_reason=cast(Any, final.stop_reason or "end_turn"),
                        usage=NormalizedUsage(
                            input_tokens=final.usage.input_tokens,
                            output_tokens=final.usage.output_tokens,
                            cache_read_tokens=getattr(
                                final.usage, "cache_read_input_tokens", 0
                            )
                            or 0,
                            cache_creation_tokens=getattr(
                                final.usage, "cache_creation_input_tokens", 0
                            )
                            or 0,
                        ),
                    )

    def estimate_cost(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
        reasoning_tokens: int = 0,
    ) -> float:
        """估算 USD 成本(reasoning_tokens 已含於 output_tokens,Anthropic 計價方式)。"""
        p = get_pricing("anthropic", self.model)
        return (
            input_tokens * p["input"] / 1e6
            + output_tokens * p["output"] / 1e6
            + cache_read_tokens * p["cache_read"] / 1e6
            + cache_creation_tokens * p.get("cache_creation", 0.0) / 1e6
        )
