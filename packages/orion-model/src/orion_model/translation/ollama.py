"""Normalized → Ollama `/api/chat` 格式翻譯。

Ollama 跟 OpenAI Chat Completions API 高度相似(都是 messages[] + role +
content),但有幾個關鍵差異:

1. **System prompt** 放在 messages[0] 的 `{"role": "system", "content": "..."}`,
   不是獨立 param
2. **Vision**:`messages[i].images = ["base64..."]` array(不是 content list 內
   `image_url`)
3. **Tool calls**:`tool_calls` 是 `{"function": {"name": ..., "arguments": dict}}`
   — `arguments` 是 **already-parsed dict**(OpenAI 是 stringified JSON)
4. **Tool result**:`{"role": "tool", "content": "..."}` — 沒有 `tool_call_id`
   欄位串接,Ollama 靠順序對應
5. **No `id` on tool calls** — Ollama 不回 id,我們自己生(從 NormalizedMessage
   的 ToolUseBlock.id 帶回去,或新生 `call_{idx}`)

Stream format 是 **NDJSON**(line-delimited)非 SSE — 解析在 ollama_provider 內。
"""

from __future__ import annotations

import re
from typing import Any

from orion_model.tool_def import ToolDefinition
from orion_model.types import (
    ImageBlock,
    NormalizedMessage,
    TextBlock,
    ThinkingBlock,
    TombstoneBlock,
    ToolResultBlock,
    ToolUseBlock,
)


def translate_messages_to_ollama(
    messages: list[NormalizedMessage],
    *,
    system: str | None = None,
) -> list[dict[str, Any]]:
    """NormalizedMessage[] → Ollama `/api/chat` messages 格式。

    Args:
        messages: 訊息歷史。role=system 會被過濾(system 透過 system 參數送)。
        system: 系統 prompt(若有,前置成第一個 system message)。
    """
    result: list[dict[str, Any]] = []

    if system:
        result.append({"role": "system", "content": system})

    for m in messages:
        if m.role == "system":
            continue  # 已由 system 參數處理

        if isinstance(m.content, str):
            result.append({"role": m.role, "content": m.content})
            continue

        # list of blocks
        text_parts: list[str] = []
        images: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        tool_results: list[dict[str, Any]] = []  # 每個 ToolResultBlock 拆獨立 message

        for block in m.content:
            if isinstance(block, TextBlock):
                text_parts.append(block.text)
            elif isinstance(block, ImageBlock):
                # Ollama images 是 raw base64,不要 data URL prefix
                images.append(block.data)
            elif isinstance(block, ToolUseBlock):
                tool_calls.append({
                    "function": {
                        "name": block.name,
                        "arguments": block.input,
                    },
                })
            elif isinstance(block, ToolResultBlock):
                content_str = (
                    block.content
                    if isinstance(block.content, str)
                    else "".join(
                        b.text if isinstance(b, TextBlock) else "[image]"
                        for b in block.content
                    )
                )
                if block.is_error:
                    content_str = f"[error] {content_str}"
                tool_results.append({"role": "tool", "content": content_str})
            elif isinstance(block, ThinkingBlock):
                # Ollama 沒 thinking channel,client 不該回送(模型自己 emit 的)
                continue
            elif isinstance(block, TombstoneBlock):
                text_parts.append(
                    "[Earlier conversation auto-compacted to summary]\n"
                    + block.summary,
                )

        # Assistant message with tool calls / images / text
        if m.role == "assistant" and (text_parts or tool_calls):
            msg: dict[str, Any] = {"role": "assistant", "content": "\n".join(text_parts)}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            result.append(msg)
        elif m.role == "user" and (text_parts or images):
            msg = {"role": "user", "content": "\n".join(text_parts)}
            if images:
                msg["images"] = images
            result.append(msg)
        # Tool results 永遠拆獨立 message(role=tool),Ollama 按順序對應到前面
        # assistant 的 tool_calls
        for tr in tool_results:
            result.append(tr)

    return result


def translate_tools_to_ollama(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    """ToolDefinition[] → Ollama `/api/chat` tools 格式。

    Ollama 用 OpenAI-compatible function schema:
        {"type": "function", "function": {"name": ..., "description": ..., "parameters": <JSON Schema>}}
    """
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


# ─── Stream parsing helpers(NDJSON content → NormalizedEvent)─────────


_THINK_OPEN = re.compile(r"<think>", re.IGNORECASE)
_THINK_CLOSE = re.compile(r"</think>", re.IGNORECASE)


def split_thinking_from_content(content: str, in_thinking: bool) -> tuple[list[tuple[str, str]], bool]:
    """切 `<think>...</think>` 出來成 thinking_delta,其餘成 text_delta。

    某些 Ollama model(DeepSeek-R1 family)inline emit `<think>...</think>`
    block 在 content。Caller 維護 `in_thinking` state 跨 NDJSON 行傳入。

    Returns:
        (parts, new_in_thinking) — parts 是 list of (kind, text)
        其中 kind in {"text", "thinking"}。
    """
    parts: list[tuple[str, str]] = []
    pos = 0
    while pos < len(content):
        if in_thinking:
            m = _THINK_CLOSE.search(content, pos)
            if m is None:
                parts.append(("thinking", content[pos:]))
                pos = len(content)
            else:
                if m.start() > pos:
                    parts.append(("thinking", content[pos:m.start()]))
                in_thinking = False
                pos = m.end()
        else:
            m = _THINK_OPEN.search(content, pos)
            if m is None:
                parts.append(("text", content[pos:]))
                pos = len(content)
            else:
                if m.start() > pos:
                    parts.append(("text", content[pos:m.start()]))
                in_thinking = True
                pos = m.end()
    return parts, in_thinking


__all__ = [
    "translate_messages_to_ollama",
    "translate_tools_to_ollama",
    "split_thinking_from_content",
]
