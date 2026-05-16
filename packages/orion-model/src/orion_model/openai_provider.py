"""OpenAI provider — 直接呼 OpenAI Responses API HTTP 端點。

不用 OpenAI Agents SDK,只用 openai 套件(薄 HTTP wrapper)。
Responses API ≠ chat.completions:input 是 list of items(message / function_call /
function_call_output)。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, cast

from openai import AsyncOpenAI

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
from orion_model.translation.openai import (
    translate_messages_to_openai,
    translate_tools_to_openai,
)
from orion_model.types import NormalizedMessage

_DEFAULT_CONTEXT_TOKENS = 128_000


class OpenAIProvider:
    """直接呼 OpenAI Responses API。"""

    name = "openai"

    def __init__(
        self,
        model: str = "gpt-5",
        client: AsyncOpenAI | None = None,
    ) -> None:
        self.model = model
        self.client = client or AsyncOpenAI()
        self.capabilities = ProviderCapabilities(
            prompt_caching=False,
            auto_caching=True,
            parallel_tool_calls=True,
            native_mcp=True,
            structured_output=True,
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
        cache_breakpoints: list[int] | None = None,  # noqa: ARG002 — 忽略,OpenAI 自動 cache
        reasoning_effort: ReasoningEffort | None = None,
    ) -> AsyncIterator[NormalizedEvent]:
        """yield NormalizedEvent。

        Phase 16:OpenAI SDK 的 stream object 沒提供 `async with`,中途被 cancel 時
        必須手動 aclose 才能關連線。用 try/finally + getattr aclose 兼容不同版本 SDK。
        """
        # OpenAI 不支 cache_control,system list 拼成單字串
        system_str = system if isinstance(system, str) else "\n\n".join(system)

        openai_input = translate_messages_to_openai(messages, system=system_str)
        openai_tools = translate_tools_to_openai(tools or [])

        # Debug — 計每筆 input item 的 input_image 數量,印 system_str 前 80 字。
        import sys as _sys
        _img_count = 0
        for _it in openai_input:
            _content = _it.get("content") if isinstance(_it, dict) else None
            if isinstance(_content, list):
                for _b in _content:
                    if isinstance(_b, dict) and _b.get("type") == "input_image":
                        _img_count += 1
        print(
            f"[openai] stream model={self.model} input_items={len(openai_input)} "
            f"images_in_input={_img_count} sys_head={system_str[:80]!r}",
            file=_sys.stderr, flush=True,
        )

        extra: dict[str, Any] = {}
        if temperature is not None:
            extra["temperature"] = temperature
        if self.capabilities.reasoning_blocks and reasoning_effort:
            extra["reasoning"] = {"effort": reasoning_effort}

        # 直接呼 OpenAI Responses API
        stream_obj = await self.client.responses.create(
            model=self.model,
            input=cast(Any, openai_input),
            tools=cast(Any, openai_tools) if openai_tools else cast(Any, None),
            stream=True,
            max_output_tokens=max_tokens,
            **extra,
        )

        current_block_idx: int | None = None
        current_tool_id: str | None = None
        current_tool_name: str | None = None
        current_partial_args = ""

        try:
            async for raw_event in stream_obj:
                # SDK streaming events 是 union type;mypy strict 無法 narrow
                # string discriminator,所以邊界視為 Any。emit 出去的
                # NormalizedEvent 仍會被 strict 檢查。
                event: Any = raw_event
                etype: str = event.type

                if etype == "response.created":
                    yield MessageStartEvent(
                        message_id=event.response.id,
                        model=self.model,
                    )

                elif etype == "response.output_text.delta":
                    yield TextDeltaEvent(text=event.delta)

                elif etype == "response.reasoning.delta":
                    yield ThinkingDeltaEvent(text=event.delta)

                elif etype == "response.output_item.added":
                    item = event.item
                    if getattr(item, "type", None) == "function_call":
                        current_block_idx = event.output_index
                        current_tool_id = item.call_id
                        current_tool_name = item.name
                        current_partial_args = ""
                        yield ToolUseStartEvent(
                            block_index=current_block_idx,
                            tool_use_id=current_tool_id,
                            tool_name=current_tool_name,
                        )

                elif etype == "response.function_call_arguments.delta":
                    current_partial_args += event.delta
                    yield ToolUseInputDeltaEvent(
                        block_index=current_block_idx or 0,
                        partial_json=event.delta,
                    )

                elif etype == "response.output_item.done":
                    item = event.item
                    if (
                        getattr(item, "type", None) == "function_call"
                        and current_tool_id is not None
                        and current_tool_name is not None
                    ):
                        try:
                            full_input = (
                                json.loads(current_partial_args) if current_partial_args else {}
                            )
                        except json.JSONDecodeError:
                            full_input = {"_parse_error": current_partial_args}
                        yield ToolUseStopEvent(
                            block_index=current_block_idx or 0,
                            tool_use_id=current_tool_id,
                            tool_name=current_tool_name,
                            full_input=full_input,
                        )
                        current_tool_id = None
                        current_tool_name = None

                elif etype == "response.completed":
                    response = event.response
                    stop_reason = self._map_stop_reason(
                        getattr(response, "status", None),
                        getattr(response, "incomplete_details", None),
                    )
                    usage = response.usage
                    input_details = getattr(usage, "input_tokens_details", None)
                    output_details = getattr(usage, "output_tokens_details", None)
                    cached = (
                        (getattr(input_details, "cached_tokens", 0) or 0)
                        if input_details
                        else 0
                    )
                    reasoning = (
                        (getattr(output_details, "reasoning_tokens", 0) or 0)
                        if output_details
                        else 0
                    )
                    # OpenAI 的 input_tokens 含 cached(Anthropic 是 disjoint)—
                    # 統一語義扣掉,讓累積 stats / cache_hit_rate 公式跨 provider 一致。
                    fresh_input = max(0, usage.input_tokens - cached)
                    yield MessageStopEvent(
                        stop_reason=cast(Any, stop_reason),
                        usage=NormalizedUsage(
                            input_tokens=fresh_input,
                            output_tokens=usage.output_tokens,
                            cache_read_tokens=cached,
                            cache_creation_tokens=0,
                            reasoning_tokens=reasoning,
                        ),
                    )
        finally:
            # Phase 16:中途 cancel 時手動關 stream 釋放 httpx connection
            aclose = getattr(stream_obj, "aclose", None) or getattr(stream_obj, "close", None)
            if aclose is not None:
                try:
                    result = aclose()
                    if hasattr(result, "__await__"):
                        await result
                except Exception:  # noqa: BLE001
                    pass

    @staticmethod
    def _map_stop_reason(status: str | None, incomplete: Any) -> str:
        """OpenAI status → normalized stop_reason。"""
        if status == "completed":
            return "end_turn"
        if incomplete is not None and getattr(incomplete, "reason", None) == "max_output_tokens":
            return "max_tokens"
        if status == "incomplete":
            return "error"
        return "end_turn"

    def estimate_cost(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,  # noqa: ARG002 — OpenAI 沒 cache_creation 概念
        reasoning_tokens: int = 0,  # noqa: ARG002 — 已含於 output_tokens
    ) -> float:
        """估算 USD 成本。reasoning_tokens 已計入 output_tokens(OpenAI 計價方式)。"""
        p = get_pricing("openai", self.model)
        return (
            input_tokens * p["input"] / 1e6
            + output_tokens * p["output"] / 1e6
            + cache_read_tokens * p["cache_read"] / 1e6
        )
