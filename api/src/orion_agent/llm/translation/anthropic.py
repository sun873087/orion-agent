"""Normalized → Anthropic 格式翻譯。"""

from __future__ import annotations

from typing import Any

from orion_agent.llm.tool_def import ToolDefinition
from orion_agent.llm.types import (
    ContentBlock,
    ImageBlock,
    NormalizedMessage,
    TextBlock,
    ThinkingBlock,
    TombstoneBlock,
    ToolResultBlock,
    ToolUseBlock,
)


def translate_messages_to_anthropic(messages: list[NormalizedMessage]) -> list[dict[str, Any]]:
    """NormalizedMessage[] → Anthropic messages format。

    注意:Anthropic system 在 top-level,**不在 messages 內**,所以 role=system 過濾掉。
    """
    result: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "system":
            continue  # Anthropic system 在 top-level
        if isinstance(m.content, str):
            result.append({"role": m.role, "content": m.content})
            continue
        # list of blocks
        result.append(
            {
                "role": m.role,
                "content": [_block_to_anthropic(b) for b in m.content],
            }
        )
    return result


def _block_to_anthropic(block: ContentBlock) -> dict[str, Any]:
    """單一 ContentBlock → Anthropic format。"""
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    if isinstance(block, ToolUseBlock):
        return {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": block.input,
        }
    if isinstance(block, ToolResultBlock):
        return {
            "type": "tool_result",
            "tool_use_id": block.tool_use_id,
            "content": block.content,
            "is_error": block.is_error,
        }
    if isinstance(block, ImageBlock):
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": block.media_type,
                "data": block.data,
            },
        }
    if isinstance(block, ThinkingBlock):
        return {"type": "thinking", "thinking": block.text}
    if isinstance(block, TombstoneBlock):
        # API 不認 tombstone — 送成普通 text 即可,模型靠 summary 上下文
        return {
            "type": "text",
            "text": (
                "[Earlier conversation auto-compacted to summary]\n"
                + block.summary
            ),
        }
    raise ValueError(f"Unknown block type: {type(block).__name__}")


def translate_tools_to_anthropic(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    """ToolDefinition[] → Anthropic tools format。"""
    result: list[dict[str, Any]] = []
    for t in tools:
        tool_dict: dict[str, Any] = {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
        }
        if t.cache_control:
            tool_dict["cache_control"] = {"type": "ephemeral"}
        result.append(tool_dict)
    return result


def apply_cache_breakpoints(
    messages: list[dict[str, Any]],
    breakpoints: list[int],
) -> list[dict[str, Any]]:
    """在指定 messages index 後標 cache_control(Anthropic 限 4 個 breakpoint)。

    處理兩種 content 格式:
    - str:升級成 [{type:text, text:..., cache_control:...}](API 不收 cache_control on str)
    - list[block]:在最後一個 block 標 cache_control
    """
    for idx in breakpoints:
        if idx < 0 or idx >= len(messages):
            continue
        msg = messages[idx]
        content = msg.get("content")
        if isinstance(content, str):
            msg["content"] = [
                {
                    "type": "text",
                    "text": content,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        elif isinstance(content, list) and content:
            content[-1]["cache_control"] = {"type": "ephemeral"}
    return messages
