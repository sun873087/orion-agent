"""OpenRouter provider — 走 chat.completions API(OpenAI-compatible)。

OpenRouter 是 LLM 統一 gateway,一支 API key 接 100+ models 來自各 vendor。
用既有 `openai.AsyncOpenAI` SDK 但 base_url 指 OpenRouter,呼 chat.completions
(舊版 OpenAI 標準)— **不是** Responses API(我們既有 OpenAIProvider 用的)。

Pricing / model meta 來自 `openrouter_catalog`(動態 fetch /api/v1/models)。

Env:
  OPENROUTER_API_KEY — 必填(send 時擋,catalog list 不擋)
  ORION_OPENROUTER_REFERER — 可選,OpenRouter analytics tracking(預設 cowork.app)
  ORION_OPENROUTER_TITLE — 可選,顯示在 OpenRouter dashboard(預設 "Orion Cowork")
"""

from __future__ import annotations

import json
import os
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
from orion_model.types import (
    ContentBlock,
    ImageBlock,
    NormalizedMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_CONTEXT_TOKENS = 128_000
_DEFAULT_REFERER = "https://github.com/anthropics/orion-agent"
_DEFAULT_TITLE = "Orion Cowork"


class OpenRouterProvider:
    """OpenRouter LLM provider — chat.completions wire,動態 catalog。"""

    name = "openrouter"

    def __init__(
        self,
        model: str = "anthropic/claude-sonnet-4-5",
        client: AsyncOpenAI | None = None,
    ) -> None:
        self.model = model
        if client is None:
            referer = os.environ.get("ORION_OPENROUTER_REFERER") or _DEFAULT_REFERER
            title = os.environ.get("ORION_OPENROUTER_TITLE") or _DEFAULT_TITLE
            # proxy 透傳:ORION_MODEL_PROXY_URL 設了就走 `{proxy}/openrouter/v1`
            # (proxy 那層拿真 OPENROUTER_API_KEY 覆寫 Authorization)。Bearer 用
            # ORION_MODEL_PROXY_KEY(admin 為 user 生的 `sk-orion-*` token)。
            # 沒設 proxy 就直連 openrouter.ai,api_key 來自 OPENROUTER_API_KEY。
            proxy = os.environ.get("ORION_MODEL_PROXY_URL")
            extra_headers: dict[str, str] = {
                "HTTP-Referer": referer,
                "X-Title": title,
            }
            if proxy:
                proxy_key = os.environ.get("ORION_MODEL_PROXY_KEY")
                if proxy_key:
                    extra_headers["Authorization"] = f"Bearer {proxy_key}"
                client_id = os.environ.get("ORION_CLIENT_ID")
                if client_id:
                    extra_headers["X-Orion-Client"] = client_id
                base_url = f"{proxy.rstrip('/')}/openrouter/v1"
                # SDK 要求 api_key non-empty;proxy 那邊用真 key 覆寫,塞 placeholder
                api_key = "via-proxy"
            else:
                base_url = _OPENROUTER_BASE_URL
                api_key = os.environ.get("OPENROUTER_API_KEY") or "missing-key"
            client = AsyncOpenAI(
                base_url=base_url,
                api_key=api_key,
                default_headers=extra_headers,
            )
        self.client = client
        self.capabilities = ProviderCapabilities(
            # OpenRouter 把 prompt caching(Anthropic 概念)當 pass-through;
            # 不是所有 model 支援,且 cache_control 走 OpenAI extension 不一致,
            # 為求穩定先標 False(不依賴它,LLM 仍能跑只是不省錢)。
            prompt_caching=False,
            # 部分 model(尤其 Anthropic / Gemini)後端自動 cache;標 True 讓 SDK
            # 不重複下 cache_breakpoints
            auto_caching=True,
            parallel_tool_calls=True,
            native_mcp=False, # OpenRouter 不暴露 MCP server endpoint
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
        cache_breakpoints: list[int] | None = None, # noqa: ARG002 — 標 auto_caching 自動 cache
        reasoning_effort: ReasoningEffort | None = None,
    ) -> AsyncIterator[NormalizedEvent]:
        """Stream chat.completions response, yield NormalizedEvent。"""
        system_str = system if isinstance(system, str) else "\n\n".join(system)
        cc_messages = _translate_messages_to_chat_completions(messages, system=system_str)
        cc_tools = _translate_tools_to_chat_completions(tools or [])

        extra: dict[str, Any] = {}
        if temperature is not None:
            extra["temperature"] = temperature
        if self.capabilities.reasoning_blocks and reasoning_effort:
            # OpenRouter 用 extra_body 傳 reasoning(各 model 的 reasoning 格式不同,
            # 但 OpenRouter 統一接 "reasoning": {"effort": "..."}). 失敗 silent fallback。
            extra["extra_body"] = {"reasoning": {"effort": reasoning_effort}}

        stream_obj = await self.client.chat.completions.create(
            model=self.model,
            messages=cast(Any, cc_messages),
            tools=cast(Any, cc_tools) if cc_tools else None,
            stream=True,
            stream_options={"include_usage": True},
            max_tokens=max_tokens,
            **extra,
        )

        # 流狀態:tool_calls 用 index 累積,完成時 emit ToolUseStop
        tool_state: dict[int, _ToolCallAccum] = {}
        message_id_emitted = False
        final_usage: NormalizedUsage | None = None
        finish_reason: str | None = None

        try:
            async for raw_chunk in stream_obj:
                chunk: Any = raw_chunk
                # Final usage-only chunk(choices 通常空 list)
                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    final_usage = _extract_usage(usage)
                if not getattr(chunk, "choices", None):
                    continue
                choice = chunk.choices[0]
                delta = getattr(choice, "delta", None)
                fr = getattr(choice, "finish_reason", None)
                if fr is not None:
                    finish_reason = fr

                if delta is None:
                    continue

                # First chunk → MessageStart(用 chunk.id 當 message_id)
                if not message_id_emitted:
                    msg_id = getattr(chunk, "id", None) or ""
                    yield MessageStartEvent(message_id=msg_id, model=self.model)
                    message_id_emitted = True

                # Text content
                content = getattr(delta, "content", None)
                if isinstance(content, str) and content:
                    yield TextDeltaEvent(text=content)

                # Reasoning(部分 model 在 delta.reasoning 或 delta.reasoning_content)
                reasoning = (
                    getattr(delta, "reasoning", None)
                    or getattr(delta, "reasoning_content", None)
                )
                if isinstance(reasoning, str) and reasoning:
                    yield ThinkingDeltaEvent(text=reasoning)

                # Tool calls
                tool_calls = getattr(delta, "tool_calls", None)
                if tool_calls:
                    for tc in tool_calls:
                        # 某些 model(Gemini / 部分 OpenRouter upstream)delta.tool_calls
                        # 的 index 可能直接 = None(非 missing),要強制 int 0 fallback
                        idx_raw = getattr(tc, "index", 0)
                        idx = idx_raw if isinstance(idx_raw, int) else 0
                        accum = tool_state.get(idx)
                        if accum is None:
                            # 首次見此 idx → 應該帶 id + function.name
                            tc_id = getattr(tc, "id", None) or ""
                            fn = getattr(tc, "function", None)
                            tc_name = getattr(fn, "name", None) if fn else None
                            accum = _ToolCallAccum(
                                index=idx,
                                tool_use_id=tc_id,
                                tool_name=tc_name or "",
                                args_buffer="",
                                started=False,
                            )
                            tool_state[idx] = accum
                        # 累積 id / name(後續 chunk 可能補上)
                        new_id = getattr(tc, "id", None)
                        if new_id and not accum.tool_use_id:
                            accum.tool_use_id = new_id
                        fn = getattr(tc, "function", None)
                        if fn is not None:
                            new_name = getattr(fn, "name", None)
                            if new_name and not accum.tool_name:
                                accum.tool_name = new_name
                            args_delta = getattr(fn, "arguments", None)
                            if isinstance(args_delta, str) and args_delta:
                                if not accum.started and accum.tool_use_id and accum.tool_name:
                                    yield ToolUseStartEvent(
                                        block_index=accum.index,
                                        tool_use_id=accum.tool_use_id,
                                        tool_name=accum.tool_name,
                                    )
                                    accum.started = True
                                accum.args_buffer += args_delta
                                if accum.started:
                                    yield ToolUseInputDeltaEvent(
                                        block_index=accum.index,
                                        partial_json=args_delta,
                                    )

            # End of stream — emit ToolUseStop for any pending tool calls
            for accum in sorted(tool_state.values(), key=lambda a: a.index):
                if not accum.started:
                    # 沒收到 arguments delta(空 args 的 tool 也得算 started)
                    if accum.tool_use_id and accum.tool_name:
                        yield ToolUseStartEvent(
                            block_index=accum.index,
                            tool_use_id=accum.tool_use_id,
                            tool_name=accum.tool_name,
                        )
                        accum.started = True
                if not accum.started:
                    continue
                try:
                    full_input = (
                        json.loads(accum.args_buffer) if accum.args_buffer else {}
                    )
                except json.JSONDecodeError:
                    full_input = {"_parse_error": accum.args_buffer}
                yield ToolUseStopEvent(
                    block_index=accum.index,
                    tool_use_id=accum.tool_use_id,
                    tool_name=accum.tool_name,
                    full_input=full_input,
                )

            # MessageStop — finish_reason map + usage(沒 usage chunk 就 zero)
            yield MessageStopEvent(
                stop_reason=cast(Any, _map_stop_reason(finish_reason)),
                usage=final_usage or NormalizedUsage(
                    input_tokens=0, output_tokens=0,
                ),
            )
        finally:
            aclose = getattr(stream_obj, "aclose", None) or getattr(stream_obj, "close", None)
            if aclose is not None:
                try:
                    result = aclose()
                    if hasattr(result, "__await__"):
                        await result
                except Exception: # noqa: BLE001
                    pass

    def estimate_cost(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
        reasoning_tokens: int = 0, # noqa: ARG002 — 已含於 output_tokens
    ) -> float:
        """估算 USD 成本,查 models.json pricing(走 get_pricing)。
        未知 model fallback zero(不擋 session)。"""
        pricing = get_pricing(self.name, self.model)
        return (
            input_tokens * pricing.get("input", 0.0) / 1e6
            + output_tokens * pricing.get("output", 0.0) / 1e6
            + cache_read_tokens * pricing.get("cache_read", 0.0) / 1e6
            + cache_creation_tokens * pricing.get("cache_creation", 0.0) / 1e6
        )


class _ToolCallAccum:
    """累積 chat.completions streaming 內的單一 tool_call(按 index 對齊)。"""

    __slots__ = ("index", "tool_use_id", "tool_name", "args_buffer", "started")

    def __init__(
        self,
        index: int,
        tool_use_id: str,
        tool_name: str,
        args_buffer: str,
        started: bool,
    ) -> None:
        self.index = index
        self.tool_use_id = tool_use_id
        self.tool_name = tool_name
        self.args_buffer = args_buffer
        self.started = started


def _map_stop_reason(finish_reason: str | None) -> str:
    """chat.completions finish_reason → normalized stop_reason。"""
    if finish_reason == "stop":
        return "end_turn"
    if finish_reason == "length":
        return "max_tokens"
    if finish_reason == "tool_calls":
        return "tool_use"
    if finish_reason == "content_filter":
        return "content_filter"
    return "end_turn"


def _extract_usage(usage: Any) -> NormalizedUsage:
    """chat.completions usage → NormalizedUsage。

    OpenRouter 透傳的 usage 大概是:
      {prompt_tokens, completion_tokens, total_tokens,
       prompt_tokens_details: {cached_tokens?},
       completion_tokens_details: {reasoning_tokens?}}
    部分 model 不帶 details,值預設 0。
    """
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion = int(getattr(usage, "completion_tokens", 0) or 0)
    prompt_details = getattr(usage, "prompt_tokens_details", None)
    completion_details = getattr(usage, "completion_tokens_details", None)
    cached = 0
    reasoning = 0
    if prompt_details is not None:
        cached = int(getattr(prompt_details, "cached_tokens", 0) or 0)
    if completion_details is not None:
        reasoning = int(getattr(completion_details, "reasoning_tokens", 0) or 0)
    # 跟 OpenAIProvider 一致:input_tokens 扣掉 cached(disjoint 語義)
    fresh_input = max(0, prompt - cached)
    return NormalizedUsage(
        input_tokens=fresh_input,
        output_tokens=completion,
        cache_read_tokens=cached,
        cache_creation_tokens=0,
        reasoning_tokens=reasoning,
    )


def _translate_messages_to_chat_completions(
    messages: list[NormalizedMessage],
    *,
    system: str,
) -> list[dict[str, Any]]:
    """NormalizedMessage → chat.completions messages 格式。

    要點:
    - system → 開頭一條 role=system
    - user with str → role=user, content=str
    - user with list(text + image)→ role=user, content=list[content blocks]
    - user with tool_result blocks → 每個 result 拆成獨立 role=tool message
      (chat.completions 有專屬 tool role)
    - assistant with tool_use blocks → role=assistant, content=text_or_null,
      tool_calls=list[function_call]
    - thinking block 丟掉(chat.completions 沒對應)
    - tombstone block 當 text 處理
    """
    out: list[dict[str, Any]] = []
    if system:
        out.append({"role": "system", "content": system})
    for m in messages:
        role = m.role
        content = m.content
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            continue
        # user msg with tool_result blocks 要拆成 N 個 tool message
        if role == "user":
            # 先收 text + image 塊;tool_result 另外拆
            mixed_blocks: list[dict[str, Any]] = []
            tool_results: list[ToolResultBlock] = []
            for b in content:
                bb = cast(ContentBlock, b)
                if isinstance(bb, TextBlock):
                    mixed_blocks.append({"type": "text", "text": bb.text})
                elif isinstance(bb, ImageBlock):
                    mixed_blocks.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{bb.media_type};base64,{bb.data}",
                        },
                    })
                elif isinstance(bb, ToolResultBlock):
                    tool_results.append(bb)
                # thinking / tombstone:user msg 本來不該有
            if mixed_blocks:
                # 單一 text → 簡化為 str(部分 model 不認 [{type:text}])
                if len(mixed_blocks) == 1 and mixed_blocks[0].get("type") == "text":
                    out.append({"role": "user", "content": mixed_blocks[0]["text"]})
                else:
                    out.append({"role": "user", "content": mixed_blocks})
            for tr in tool_results:
                tc = tr.content
                if isinstance(tc, str):
                    tc_text = tc
                else:
                    parts = []
                    for inner in tc:
                        if isinstance(inner, TextBlock):
                            parts.append(inner.text)
                        # image 在 tool result 內 chat.completions 不支援,跳過
                    tc_text = "\n".join(parts)
                out.append({
                    "role": "tool",
                    "tool_call_id": tr.tool_use_id,
                    "content": tc_text,
                })
            continue
        # assistant msg with mixed blocks
        if role == "assistant":
            text_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            for b in content:
                bb = cast(ContentBlock, b)
                if isinstance(bb, TextBlock):
                    text_parts.append(bb.text)
                elif isinstance(bb, ToolUseBlock):
                    tool_calls.append({
                        "id": bb.id,
                        "type": "function",
                        "function": {
                            "name": bb.name,
                            "arguments": json.dumps(bb.input, ensure_ascii=False),
                        },
                    })
                elif isinstance(bb, ThinkingBlock):
                    # chat.completions 沒原生 thinking,丟掉
                    continue
                # tombstone 也丟,user 那條已經 inject summary 進 message
            msg: dict[str, Any] = {"role": "assistant"}
            if text_parts:
                msg["content"] = "".join(text_parts)
            else:
                # chat.completions 要 content non-null;沒 text 給 empty string
                msg["content"] = ""
            if tool_calls:
                msg["tool_calls"] = tool_calls
            out.append(msg)
            continue
        # system role in messages(罕見)— 當 text
        text_parts2: list[str] = []
        for b in content:
            if isinstance(b, TextBlock):
                text_parts2.append(b.text)
        if text_parts2:
            out.append({"role": role, "content": "".join(text_parts2)})
    return out


def _translate_tools_to_chat_completions(
    tools: list[ToolDefinition],
) -> list[dict[str, Any]]:
    """ToolDefinition → chat.completions tools 格式。"""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        }
        for t in tools
    ]
