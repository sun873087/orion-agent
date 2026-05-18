"""Ollama provider — 直接呼 Ollama HTTP API。

Ollama 是 local LLM runtime(也可遠端 server),提供 `/api/chat`、`/api/tags`
等 REST endpoint。本 provider 走 native Ollama API(不走 OpenAI-compat 端點)
以拿到完整 feature surface。

設計:
- Streaming format 是 **NDJSON**(line-delimited),非 SSE — 用 httpx 的
  `stream()` + `aiter_lines()` 解析
- Tool calling 支援度看 model 本身(Llama 3.1+ / Mistral Nemo / Qwen2.5 等
  有 tool 模板的 model 才能用)— 不支援的 model 會 silently ignore tools 欄位
- Vision 支援 — 透過 `messages[i].images = [base64...]`
- Pricing 永遠回 $0(local 不計費),token count 仍從 final NDJSON 行的
  `prompt_eval_count` / `eval_count` 拿
- `<think>...</think>` inline 在 content(DeepSeek-R1 family)在 stream 解析時
  split 出來 emit 為 `thinking_delta`

Base URL 順序(高優先到低):
1. constructor `base_url` kwarg
2. `OLLAMA_HOST` env(Ollama 自己 convention)
3. `http://localhost:11434` 預設
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from collections.abc import AsyncIterator
from typing import Any, cast

import httpx

from orion_model.catalog import get_max_context_tokens
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
from orion_model.provider import ProviderCapabilities, ReasoningEffort
from orion_model.tool_def import ToolDefinition
from orion_model.translation.ollama import (
    split_thinking_from_content,
    translate_messages_to_ollama,
    translate_tools_to_ollama,
)
from orion_model.types import NormalizedMessage

_DEFAULT_BASE_URL = "http://localhost:11434"
_DEFAULT_CONTEXT_TOKENS = 8192  # 保守 fallback;真實值看 model 自己
_REQUEST_TIMEOUT = httpx.Timeout(connect=10.0, read=600.0, write=60.0, pool=10.0)


def resolve_ollama_base_url(override: str | None = None) -> str:
    """Resolve base URL 順序:override → OLLAMA_HOST env → 預設 localhost。"""
    if override:
        return override.rstrip("/")
    env = os.environ.get("OLLAMA_HOST")
    if env:
        # OLLAMA_HOST 可能是 "host:port"(無 scheme)或完整 URL,兩種都 normalize
        if not env.startswith(("http://", "https://")):
            env = "http://" + env
        return env.rstrip("/")
    return _DEFAULT_BASE_URL


class OllamaProvider:
    """直接呼 Ollama `/api/chat` HTTP endpoint。"""

    name = "ollama"

    def __init__(
        self,
        model: str = "llama3.1:8b",
        *,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self.base_url = resolve_ollama_base_url(base_url)
        self._client = client  # None = 每 stream() 自己開 short-lived client
        self._owns_client = client is None
        self.capabilities = ProviderCapabilities(
            prompt_caching=False,
            auto_caching=False,
            parallel_tool_calls=True,  # Ollama 支援,但模型本身要有 tool 模板
            native_mcp=False,
            structured_output=False,
            reasoning_blocks=False,  # `<think>` inline 而非 native event,我們自己 split
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
        cache_breakpoints: list[int] | None = None,  # noqa: ARG002 — Ollama 無 cache
        reasoning_effort: ReasoningEffort | None = None,  # noqa: ARG002 — Ollama 無 reasoning effort
    ) -> AsyncIterator[NormalizedEvent]:
        """送 `/api/chat` streaming request,逐行 NDJSON 解析 emit NormalizedEvent。"""
        system_str = system if isinstance(system, str) else "\n\n".join(system)
        ollama_messages = translate_messages_to_ollama(messages, system=system_str)
        ollama_tools = translate_tools_to_ollama(tools or [])

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": True,
            "options": {
                "num_predict": max_tokens,
            },
        }
        if temperature is not None:
            payload["options"]["temperature"] = temperature
        if ollama_tools:
            payload["tools"] = ollama_tools

        # Debug
        _img_count = sum(len(m.get("images", [])) for m in ollama_messages if isinstance(m, dict))
        print(
            f"[ollama] stream model={self.model} base_url={self.base_url} "
            f"messages={len(ollama_messages)} images={_img_count} "
            f"tools={len(ollama_tools)} sys_head={system_str[:80]!r}",
            file=sys.stderr, flush=True,
        )

        message_id = f"ollama-{uuid.uuid4().hex[:12]}"
        yield MessageStartEvent(message_id=message_id, model=self.model)

        client = self._client or httpx.AsyncClient(timeout=_REQUEST_TIMEOUT)
        try:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=payload,
            ) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    raise httpx.HTTPStatusError(
                        f"Ollama returned {response.status_code}: "
                        f"{body.decode('utf-8', errors='replace')[:500]}",
                        request=response.request,
                        response=response,
                    )

                # Stream state
                in_thinking = False
                tool_block_idx = 0
                emitted_tool_use_ids: list[str] = []  # 追蹤 tool_calls 順序
                final_usage = NormalizedUsage(input_tokens=0, output_tokens=0)
                stop_reason: str = "end_turn"

                async for raw_line in response.aiter_lines():
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    msg = chunk.get("message", {})

                    # ─── 文字 delta ────────────────────────────────────
                    content = msg.get("content", "")
                    if content:
                        parts, in_thinking = split_thinking_from_content(content, in_thinking)
                        for kind, text in parts:
                            if not text:
                                continue
                            if kind == "thinking":
                                yield ThinkingDeltaEvent(text=text)
                            else:
                                yield TextDeltaEvent(text=text)

                    # ─── Tool calls(Ollama 在最後一筆 message 一次給,不是逐字)──
                    tool_calls = msg.get("tool_calls")
                    if isinstance(tool_calls, list):
                        for tc in tool_calls:
                            fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                            tname = fn.get("name")
                            targs = fn.get("arguments", {})
                            if not isinstance(tname, str):
                                continue
                            if not isinstance(targs, dict):
                                # 某些 model 還是回 stringified — 嘗試 parse
                                try:
                                    targs = json.loads(targs) if isinstance(targs, str) else {}
                                except (json.JSONDecodeError, TypeError):
                                    targs = {}
                            tool_use_id = tc.get("id") or f"call_{message_id}_{tool_block_idx}"
                            emitted_tool_use_ids.append(tool_use_id)
                            yield ToolUseStartEvent(
                                block_index=tool_block_idx,
                                tool_use_id=tool_use_id,
                                tool_name=tname,
                            )
                            # 一次性 emit input(NormalizedEvent 流仍要送 delta 才能對齊
                            # SDK pipeline,JSON 完整就一筆 delta + stop)
                            json_str = json.dumps(targs)
                            yield ToolUseInputDeltaEvent(
                                block_index=tool_block_idx,
                                partial_json=json_str,
                            )
                            yield ToolUseStopEvent(
                                block_index=tool_block_idx,
                                tool_use_id=tool_use_id,
                                tool_name=tname,
                                full_input=targs,
                            )
                            tool_block_idx += 1

                    # ─── 最後一筆(done=true)有 usage 跟 stop reason ──
                    if chunk.get("done"):
                        prompt_tokens = chunk.get("prompt_eval_count") or 0
                        completion_tokens = chunk.get("eval_count") or 0
                        final_usage = NormalizedUsage(
                            input_tokens=int(prompt_tokens),
                            output_tokens=int(completion_tokens),
                        )
                        # Ollama done_reason: "stop" / "length" / "load" / ...
                        done_reason = chunk.get("done_reason", "stop")
                        if done_reason == "length":
                            stop_reason = "max_tokens"
                        elif emitted_tool_use_ids:
                            stop_reason = "tool_use"
                        else:
                            stop_reason = "end_turn"

                yield MessageStopEvent(
                    stop_reason=cast(Any, stop_reason),
                    usage=final_usage,
                )
        except httpx.ConnectError as e:
            raise RuntimeError(
                f"Cannot connect to Ollama at {self.base_url} — is it running? "
                f"Start it with `ollama serve`. ({e})"
            ) from e
        finally:
            if self._owns_client:
                await client.aclose()

    def estimate_cost(
        self,
        *,
        input_tokens: int,  # noqa: ARG002 — local 不計費
        output_tokens: int,  # noqa: ARG002
        cache_read_tokens: int = 0,  # noqa: ARG002
        cache_creation_tokens: int = 0,  # noqa: ARG002
        reasoning_tokens: int = 0,  # noqa: ARG002
    ) -> float:
        """Local model 永遠 $0(GPU / 電費是隱性 cost,不在 API cost dashboard)。"""
        return 0.0


# ─── Admin helpers — 給 Cowork Settings UI / CLI 動態抓 model 列表 ─────


async def list_ollama_models(
    base_url: str | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """呼 `GET /api/tags`,回已 pull 的 model 列表。

    Returns:
        list[{name, size, modified_at, digest, details: {parameter_size, quantization_level, ...}}]
        失敗(連不上 / 非 200)raise RuntimeError。
    """
    url = f"{resolve_ollama_base_url(base_url)}/api/tags"
    owns = client is None
    c = client or httpx.AsyncClient(timeout=httpx.Timeout(10.0))
    try:
        try:
            response = await c.get(url)
        except httpx.ConnectError as e:
            raise RuntimeError(f"Cannot connect to Ollama at {url}: {e}") from e
        if response.status_code != 200:
            raise RuntimeError(
                f"Ollama returned {response.status_code} at {url}: {response.text[:200]}"
            )
        data = response.json()
        models = data.get("models", [])
        return list(models) if isinstance(models, list) else []
    finally:
        if owns:
            await c.aclose()


async def check_ollama_health(
    base_url: str | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """呼 `GET /api/version`,回 `{ok: bool, version?: str, error?: str, base_url: str}`。

    供 Cowork Settings UI 顯連線狀態 banner 用。
    """
    resolved = resolve_ollama_base_url(base_url)
    url = f"{resolved}/api/version"
    owns = client is None
    c = client or httpx.AsyncClient(timeout=httpx.Timeout(5.0))
    try:
        try:
            response = await c.get(url)
        except httpx.ConnectError as e:
            return {"ok": False, "error": str(e), "base_url": resolved}
        if response.status_code != 200:
            return {
                "ok": False,
                "error": f"HTTP {response.status_code}",
                "base_url": resolved,
            }
        data = response.json()
        return {
            "ok": True,
            "version": data.get("version", "unknown"),
            "base_url": resolved,
        }
    finally:
        if owns:
            await c.aclose()


__all__ = [
    "OllamaProvider",
    "check_ollama_health",
    "list_ollama_models",
    "resolve_ollama_base_url",
]
