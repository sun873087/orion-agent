"""Anthropic provider — 直接呼 Anthropic Messages API HTTP 端點。

不用 Anthropic Agent SDK,只用 anthropic 套件(薄 HTTP wrapper)。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, cast

from anthropic import AsyncAnthropic

from orion_agent.llm.catalog import (
    get_max_context_tokens,
    get_supports_reasoning,
)
from orion_agent.llm.events import (
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
from orion_agent.llm.pricing import get_pricing
from orion_agent.llm.provider import ProviderCapabilities, ReasoningEffort
from orion_agent.llm.tool_def import ToolDefinition
from orion_agent.llm.translation.anthropic import (
    apply_cache_breakpoints,
    translate_messages_to_anthropic,
    translate_tools_to_anthropic,
)
from orion_agent.llm.types import NormalizedMessage

_DEFAULT_CONTEXT_TOKENS = 200_000

_REASONING_BUDGET = {
    "minimal": 1024,
    "low": 4096,
    "medium": 16384,
    "high": 32768,
}


def _build_system_param(system: str | list[str]) -> str | list[dict[str, Any]]:
    """str → 直傳;list[str] → 每段都標 cache_control(Anthropic 限 4 個 bp)。

    慣例:caller 保證 list 內每段都是 cacheable(session-stable 或更穩定)。
    volatile per-turn 內容應由 caller 注入 user message,不放在 system list。

    每段標 cache_control 讓多層 cache 各自獨立比對:
    - block[0] = static prompt(跨 session 不變)→ 寫入 cache 1
    - block[1] = session-stable dynamic → 寫入 cache 2
    - 若 caller 多送幾段(例如 user-level / conversation-level)→ cache 3, 4

    空字串段會跳過 cache_control(API 拒收 cache_control on empty block)。
    """
    if isinstance(system, str):
        return system
    blocks: list[dict[str, Any]] = []
    for s in system:
        block: dict[str, Any] = {"type": "text", "text": s}
        if s.strip():
            block["cache_control"] = {"type": "ephemeral"}
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
        self.client = client or AsyncAnthropic()
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
        """yield NormalizedEvent。"""
        anthropic_messages = translate_messages_to_anthropic(messages)
        anthropic_tools = translate_tools_to_anthropic(tools or [])

        # System prompt:str 或 list[str](cache_control 邏輯見 _build_system_param)
        system_param = _build_system_param(system)

        if cache_breakpoints:
            anthropic_messages = apply_cache_breakpoints(anthropic_messages, cache_breakpoints)

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
