"""Google Gemini provider — 走 native Gemini API(`generateContent` / `streamGenerateContent`)。

**不**用 OpenAI-compat 端點 — 那邊歷史 function_call 沒 thought_signature 會 400。
Native API 我們**完整管 thought_signature 跨 turn 來回 echo**。

Endpoint:
  POST https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse
Auth: `x-goog-api-key: {GEMINI_API_KEY}` header(直連)或 Bearer(經 proxy)
Wire 格式 — 跟 OpenAI / Anthropic 都不同:
  - system → `systemInstruction.parts[].text`
  - messages → `contents[]` with role="user"|"model" + parts[]
  - parts 可以是 {text}, {inlineData:{mimeType,data}}, {functionCall:{name,args}, thoughtSignature?},
    {functionResponse:{name,response}}
  - tools → `tools[].functionDeclarations[].{name,description,parameters}`
  - generationConfig.thinkingConfig.thinkingBudget=0 關 thinking(非 reasoning model)

Streaming(`?alt=sse`):
  data: {chunk1_json}\n\n
  data: {chunk2_json}\n\n
  ...
每筆 chunk 是完整 JSON({candidates:[{content:{parts}, finishReason?}], usageMetadata?})。
function_call 在一筆 chunk 內整包來(不分段),text 可以跨 chunk 增量。

Env:
  GEMINI_API_KEY — 必填(跟 GOOGLE_STT_API_KEY 區隔)
  ORION_MODEL_PROXY_URL — 設了走 `{proxy}/google/v1beta/...`
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any, cast

import httpx

from orion_model.catalog import (
    get_max_context_tokens,
    get_supports_reasoning,
)
from orion_model.errors import ProviderHTTPError
from orion_model.events import (
    MessageStartEvent,
    MessageStopEvent,
    NormalizedEvent,
    NormalizedUsage,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ToolUseInputDeltaEvent, # noqa: F401 — keep import for symmetry with other providers
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
    ToolResultBlock,
    ToolUseBlock,
)

_GOOGLE_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
_DEFAULT_CONTEXT_TOKENS = 1_000_000


class GoogleProvider:
    """Native Gemini API provider。"""

    name = "google"

    def __init__(
        self,
        model: str = "gemini-3.5-flash",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self._client = client # None → lazy create per-stream
        self.capabilities = ProviderCapabilities(
            prompt_caching=False,
            auto_caching=True, # Gemini 後端 implicit context caching
            parallel_tool_calls=True,
            native_mcp=False,
            structured_output=True,
            reasoning_blocks=get_supports_reasoning(self.name, model),
            max_context_tokens=get_max_context_tokens(self.name, model)
            or _DEFAULT_CONTEXT_TOKENS,
        )

    def _build_url_and_headers(self) -> tuple[str, dict[str, str]]:
        """回 (endpoint URL, headers)。走 proxy 時用 Bearer + proxy base;否則
        直連 Gemini + x-goog-api-key。"""
        proxy = os.environ.get("ORION_MODEL_PROXY_URL")
        endpoint = f"models/{self.model}:streamGenerateContent"
        if proxy:
            url = f"{proxy.rstrip('/')}/google/v1beta/{endpoint}"
            headers: dict[str, str] = {}
            proxy_key = os.environ.get("ORION_MODEL_PROXY_KEY")
            if proxy_key:
                headers["Authorization"] = f"Bearer {proxy_key}"
            client_id = os.environ.get("ORION_CLIENT_ID")
            if client_id:
                headers["X-Orion-Client"] = client_id
            return url, headers
        api_key = os.environ.get("GEMINI_API_KEY") or "missing-key"
        url = f"{_GOOGLE_API_BASE}/{endpoint}"
        return url, {"x-goog-api-key": api_key}

    async def stream(
        self,
        *,
        system: str | list[str],
        messages: list[NormalizedMessage],
        tools: list[ToolDefinition] | None = None,
        max_tokens: int = 4096,
        temperature: float | None = None,
        cache_breakpoints: list[int] | None = None, # noqa: ARG002 — auto cache
        reasoning_effort: ReasoningEffort | None = None,
    ) -> AsyncIterator[NormalizedEvent]:
        system_str = system if isinstance(system, str) else "\n\n".join(system)
        contents = _translate_messages_to_gemini(messages)
        gemini_tools = _translate_tools_to_gemini(tools or [])

        generation_config: dict[str, Any] = {"maxOutputTokens": max_tokens}
        if temperature is not None:
            generation_config["temperature"] = temperature
        # Thinking 設定:reasoning model + 指定 effort → 留 budget(粗對應);
        # 否則 budget=0 完全關(避開 thought_signature 機制簡化 multi-turn)。
        if self.capabilities.reasoning_blocks and reasoning_effort:
            budget = _REASONING_EFFORT_TO_BUDGET.get(reasoning_effort, 1024)
            generation_config["thinkingConfig"] = {
                "thinkingBudget": budget,
                "includeThoughts": True,
            }
        else:
            generation_config["thinkingConfig"] = {"thinkingBudget": 0}

        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": generation_config,
        }
        if system_str:
            body["systemInstruction"] = {"parts": [{"text": system_str}]}
        if gemini_tools:
            body["tools"] = gemini_tools

        url, headers = self._build_url_and_headers()

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=httpx.Timeout(600.0, read=300.0))
        message_id_emitted = False
        # 收 streaming chunks 內可能跨 chunk 累積的 text;function_call 一筆 chunk
        # 內完整,直接 emit Start + Stop。
        block_counter = 0
        final_usage: NormalizedUsage | None = None
        final_finish_reason: str | None = None

        try:
            async with client.stream(
                "POST",
                url,
                json=body,
                headers=headers,
                params={"alt": "sse"},
            ) as resp:
                if resp.status_code >= 400:
                    # 讀完 body parse 出 upstream message,raise typed error
                    # 給 sidecar `_format_send_error` 識別,UI 看到中文友善訊息
                    err_bytes = await resp.aread()
                    err_text = err_bytes.decode("utf-8", errors="replace")
                    upstream_msg = ""
                    try:
                        parsed = json.loads(err_text)
                        if isinstance(parsed, dict):
                            err_obj = parsed.get("error") or {}
                            if isinstance(err_obj, dict):
                                upstream_msg = err_obj.get("message", "") or ""
                    except (json.JSONDecodeError, ValueError):
                        pass
                    raise ProviderHTTPError(
                        provider="google",
                        status_code=resp.status_code,
                        upstream_message=upstream_msg,
                        body=err_text,
                    )
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    payload = line[len("data:"):].strip()
                    if not payload:
                        continue
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue

                    if not message_id_emitted:
                        msg_id = chunk.get("responseId") or ""
                        yield MessageStartEvent(message_id=msg_id, model=self.model)
                        message_id_emitted = True

                    # 解 candidates[0].content.parts[]
                    candidates = chunk.get("candidates") or []
                    if candidates:
                        cand = candidates[0]
                        content = cand.get("content") or {}
                        parts = content.get("parts") or []
                        for part in parts:
                            if not isinstance(part, dict):
                                continue
                            # Thinking text(reasoning model)
                            if part.get("thought") and isinstance(part.get("text"), str):
                                yield ThinkingDeltaEvent(text=part["text"])
                                continue
                            # 純 text
                            if isinstance(part.get("text"), str):
                                yield TextDeltaEvent(text=part["text"])
                                continue
                            # Function call(整包來,不分段)
                            fc = part.get("functionCall")
                            if isinstance(fc, dict):
                                tool_name = fc.get("name") or ""
                                tool_args = fc.get("args") or {}
                                if not isinstance(tool_args, dict):
                                    tool_args = {}
                                # Gemini native API 不給 tool_use_id,用 block index 當穩定 id
                                tool_use_id = f"gemini_call_{block_counter}"
                                signature = part.get("thoughtSignature")
                                yield ToolUseStartEvent(
                                    block_index=block_counter,
                                    tool_use_id=tool_use_id,
                                    tool_name=tool_name,
                                )
                                # 把 thought_signature 透過 full_input 帶出去 —
                                # caller(query_loop)會把 full_input 寫進
                                # ToolUseBlock.input,我們用一個 _thought_signature
                                # 特殊 key 保存,_translate_messages 回程時再讀出來。
                                # 不污染真實 tool input(reserved underscore prefix)。
                                full_input = dict(tool_args)
                                if isinstance(signature, str) and signature:
                                    full_input["__thought_signature__"] = signature
                                yield ToolUseStopEvent(
                                    block_index=block_counter,
                                    tool_use_id=tool_use_id,
                                    tool_name=tool_name,
                                    full_input=full_input,
                                )
                                block_counter += 1
                                continue
                        fr = cand.get("finishReason")
                        if isinstance(fr, str):
                            final_finish_reason = fr

                    # Usage(可能在每筆 chunk 都帶,最後一筆是 final)
                    usage_meta = chunk.get("usageMetadata")
                    if isinstance(usage_meta, dict):
                        final_usage = NormalizedUsage(
                            input_tokens=int(usage_meta.get("promptTokenCount") or 0),
                            output_tokens=int(usage_meta.get("candidatesTokenCount") or 0),
                            cache_read_tokens=int(
                                usage_meta.get("cachedContentTokenCount") or 0
                            ),
                            cache_creation_tokens=0,
                            reasoning_tokens=int(
                                usage_meta.get("thoughtsTokenCount") or 0
                            ),
                        )
            yield MessageStopEvent(
                stop_reason=cast(Any, _map_finish_reason(final_finish_reason)),
                usage=final_usage or NormalizedUsage(input_tokens=0, output_tokens=0),
            )
        finally:
            if owns_client:
                await client.aclose()

    def estimate_cost(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
        reasoning_tokens: int = 0, # noqa: ARG002 — 已含 output
    ) -> float:
        pricing = get_pricing(self.name, self.model)
        return (
            input_tokens * pricing.get("input", 0.0) / 1e6
            + output_tokens * pricing.get("output", 0.0) / 1e6
            + cache_read_tokens * pricing.get("cache_read", 0.0) / 1e6
            + cache_creation_tokens * pricing.get("cache_creation", 0.0) / 1e6
        )


# 粗對應 — Gemini thinkingBudget 是 token 數(0 / 1024 / 8192 / 24576 等)
_REASONING_EFFORT_TO_BUDGET = {
    "minimal": 1024,
    "low": 4096,
    "medium": 16384,
    "high": 32768,
}


def _map_finish_reason(fr: str | None) -> str:
    """Gemini finishReason → normalized stop_reason。"""
    if fr in (None, "STOP"):
        return "end_turn"
    if fr == "MAX_TOKENS":
        return "max_tokens"
    if fr == "SAFETY":
        return "content_filter"
    if fr == "RECITATION":
        return "content_filter"
    return "end_turn"


def _translate_tools_to_gemini(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    """ToolDefinition → Gemini tools 格式:[{functionDeclarations:[...]}]。

    Gemini 把所有 functions 包進**一個** tool 物件的 functionDeclarations list,
    跟 OpenAI / Anthropic 平鋪不同。
    """
    if not tools:
        return []
    decls: list[dict[str, Any]] = []
    for t in tools:
        decls.append({
            "name": t.name,
            "description": t.description,
            "parameters": _clean_schema_for_gemini(t.input_schema),
        })
    return [{"functionDeclarations": decls}]


_DROP_KEYS = frozenset({
    # $-prefixed JSON-Schema meta
    "$schema", "$defs", "$id", "$comment", "$anchor", "$dynamicRef", "$dynamicAnchor",
    # alt name for $defs
    "definitions",
    # Gemini 不認的 keyword(OpenAPI 3.0 subset)
    "title", "additionalProperties", "default",
    "exclusiveMinimum", "exclusiveMaximum",
    "examples", "const", "readOnly", "writeOnly",
    "patternProperties", "dependencies", "dependentSchemas", "dependentRequired",
    "discriminator", "deprecated",
    "contentEncoding", "contentMediaType", "contentSchema",
    "unevaluatedProperties", "unevaluatedItems",
})


def _clean_schema_for_gemini(schema: dict[str, Any]) -> dict[str, Any]:
    """Pydantic JSON Schema → Gemini OpenAPI 3.0 subset。

    兩件事:
    1. **Inline `$ref`**(Gemini 沒 ref resolution)— 從 root schema 內的 `$defs`/
       `definitions` 找 target 替換進去
    2. 砍掉所有 Gemini 不認的 keyword(`_DROP_KEYS`)
    """
    if not isinstance(schema, dict):
        return {}
    defs: dict[str, Any] = {}
    if isinstance(schema.get("$defs"), dict):
        defs.update(schema["$defs"])
    if isinstance(schema.get("definitions"), dict):
        defs.update(schema["definitions"])
    return _walk_clean(schema, defs)


def _walk_clean(node: Any, defs: dict[str, Any]) -> Any:
    """Recursive clean — 解 $ref 後再砍 keyword,順便清 enum 內空字串。"""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            target: dict[str, Any] | None = None
            for prefix in ("#/$defs/", "#/definitions/"):
                if ref.startswith(prefix):
                    key = ref[len(prefix):]
                    if isinstance(defs.get(key), dict):
                        target = defs[key]
                    break
            if target is not None:
                # 解 ref 後繼續 walk(target 可能含 nested $ref)
                return _walk_clean(target, defs)
            return {} # unknown ref → 空 schema(讓 Gemini 視為 any)
        out: dict[str, Any] = {}
        for k, v in node.items():
            if k in _DROP_KEYS:
                continue
            out[k] = _walk_clean(v, defs)
        # Gemini 拒 enum 含空字串 / null — Pydantic 對 Literal["", "a", ...] 會生
        # 出空字串值;filter 掉,filter 完是空 list 就砍 enum key
        if isinstance(out.get("enum"), list):
            filtered = [
                v for v in out["enum"]
                if v is not None and not (isinstance(v, str) and v == "")
            ]
            if filtered:
                out["enum"] = filtered
            else:
                out.pop("enum", None)
        return out
    if isinstance(node, list):
        return [_walk_clean(x, defs) for x in node]
    return node


def _translate_messages_to_gemini(
    messages: list[NormalizedMessage],
) -> list[dict[str, Any]]:
    """NormalizedMessage → Gemini contents 格式。

    Gemini 規則:
    - role: "user" | "model"(沒 "assistant"/"system")
    - parts: 各種 part dict({text} / {inlineData} / {functionCall, thoughtSignature?}
      / {functionResponse})
    - User msg with ToolResultBlock → 拆成 role=user 但 parts 是 functionResponse;
      Gemini 期待 functionResponse 的 `name` 對應之前那 functionCall 的 name
    - Assistant msg with ToolUseBlock → role=model parts=[{functionCall, thoughtSignature}]
      thoughtSignature 從 ToolUseBlock.thought_signature 拿(若有);否則略
    """
    # 先建 tool_use_id → tool_name map(給 ToolResultBlock 拼 functionResponse 用)
    tool_use_id_to_name: dict[str, str] = {}
    tool_use_id_to_signature: dict[str, str] = {}
    for m in messages:
        if m.role != "assistant":
            continue
        if isinstance(m.content, list):
            for b in m.content:
                if isinstance(b, ToolUseBlock):
                    tool_use_id_to_name[b.id] = b.name
                    # signature 可能存在 input 內 (__thought_signature__) 或直接欄位
                    sig = b.thought_signature
                    if sig is None and isinstance(b.input, dict):
                        sig = b.input.get("__thought_signature__")
                    if isinstance(sig, str) and sig:
                        tool_use_id_to_signature[b.id] = sig

    contents: list[dict[str, Any]] = []
    for m in messages:
        role = "user" if m.role == "user" else "model"
        if isinstance(m.content, str):
            if m.content:
                contents.append({"role": role, "parts": [{"text": m.content}]})
            continue
        if not isinstance(m.content, list):
            continue
        parts: list[dict[str, Any]] = []
        for b in m.content:
            bb = cast(ContentBlock, b)
            if isinstance(bb, TextBlock):
                if bb.text:
                    parts.append({"text": bb.text})
            elif isinstance(bb, ImageBlock):
                parts.append({
                    "inlineData": {
                        "mimeType": bb.media_type,
                        "data": bb.data,
                    },
                })
            elif isinstance(bb, ToolUseBlock):
                # 從 input 抽掉 internal signature key
                clean_args = {k: v for k, v in bb.input.items() if k != "__thought_signature__"}
                part: dict[str, Any] = {
                    "functionCall": {
                        "name": bb.name,
                        "args": clean_args,
                    },
                }
                sig = bb.thought_signature
                if sig is None and isinstance(bb.input, dict):
                    sig = bb.input.get("__thought_signature__")
                if isinstance(sig, str) and sig:
                    part["thoughtSignature"] = sig
                parts.append(part)
            elif isinstance(bb, ToolResultBlock):
                # functionResponse 需要 name — 從 tool_use_id 反查
                fn_name = tool_use_id_to_name.get(bb.tool_use_id, "unknown")
                if isinstance(bb.content, str):
                    response_value: dict[str, Any] = {"output": bb.content}
                else:
                    text_parts: list[str] = []
                    for inner in bb.content:
                        if isinstance(inner, TextBlock):
                            text_parts.append(inner.text)
                    response_value = {"output": "\n".join(text_parts)}
                parts.append({
                    "functionResponse": {
                        "name": fn_name,
                        "response": response_value,
                    },
                })
        if parts:
            contents.append({"role": role, "parts": parts})
    return contents
