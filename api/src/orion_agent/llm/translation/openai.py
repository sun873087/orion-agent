"""Normalized → OpenAI Responses API 格式翻譯。

OpenAI Responses API input 是 list of items(message / function_call / function_call_output)。
與 chat.completions API 完全不同 — 別把 chat.completions 教學 copy 到這裡。
"""

from __future__ import annotations

import json
from typing import Any

from orion_agent.llm.tool_def import ToolDefinition
from orion_agent.llm.types import (
    ImageBlock,
    NormalizedMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)


def translate_messages_to_openai(
    messages: list[NormalizedMessage],
    *,
    system: str | None = None,
) -> list[dict[str, Any]]:
    """NormalizedMessage[] → OpenAI Responses API input items。

    Args:
        messages: 訊息歷史。role=system 會被過濾(OpenAI system 透過 system 參數送)。
        system: 系統 prompt(若有,前置成第一個 system message item)。
    """
    result: list[dict[str, Any]] = []

    if system:
        result.append(
            {
                "type": "message",
                "role": "system",
                "content": [{"type": "input_text", "text": system}],
            }
        )

    for m in messages:
        if m.role == "system":
            continue  # 已由 system 參數處理

        if isinstance(m.content, str):
            text_type = "input_text" if m.role == "user" else "output_text"
            result.append(
                {
                    "type": "message",
                    "role": m.role,
                    "content": [{"type": text_type, "text": m.content}],
                }
            )
            continue

        # list of blocks → 拆成多個 items(text / image 進 message,
        # tool_use / tool_result 是獨立 items)
        message_content: list[dict[str, Any]] = []

        for block in m.content:
            if isinstance(block, TextBlock):
                text_type = "input_text" if m.role == "user" else "output_text"
                message_content.append({"type": text_type, "text": block.text})
            elif isinstance(block, ImageBlock):
                # data URL 格式
                message_content.append(
                    {
                        "type": "input_image",
                        "image_url": f"data:{block.media_type};base64,{block.data}",
                    }
                )
            elif isinstance(block, ToolUseBlock):
                # 先 flush 現有 message content
                if message_content:
                    result.append(
                        {"type": "message", "role": m.role, "content": message_content}
                    )
                    message_content = []
                result.append(
                    {
                        "type": "function_call",
                        "call_id": block.id,
                        "name": block.name,
                        "arguments": json.dumps(block.input),
                    }
                )
            elif isinstance(block, ToolResultBlock):
                if message_content:
                    result.append(
                        {"type": "message", "role": m.role, "content": message_content}
                    )
                    message_content = []
                output_str = (
                    block.content
                    if isinstance(block.content, str)
                    else json.dumps(block.content)
                )
                result.append(
                    {
                        "type": "function_call_output",
                        "call_id": block.tool_use_id,
                        "output": output_str,
                    }
                )
            elif isinstance(block, ThinkingBlock):
                # OpenAI 的 reasoning 是模型自己 emit 的,client 不該回送
                continue

        if message_content:
            result.append({"type": "message", "role": m.role, "content": message_content})

    return result


def translate_tools_to_openai(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    """ToolDefinition[] → OpenAI Responses API tools format。"""
    return [
        {
            "type": "function",
            "name": t.name,
            "description": t.description,
            "parameters": t.input_schema,
        }
        for t in tools
    ]
