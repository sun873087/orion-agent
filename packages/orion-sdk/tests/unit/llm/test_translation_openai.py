"""Normalized → OpenAI Responses API 翻譯。"""

from __future__ import annotations

import json

from orion_model.tool_def import ToolDefinition
from orion_model.translation.openai import (
    translate_messages_to_openai,
    translate_tools_to_openai,
)
from orion_model.types import (
    NormalizedMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)


def test_user_text_uses_input_text() -> None:
    msgs = [NormalizedMessage(role="user", content="hello")]
    out = translate_messages_to_openai(msgs)
    assert out == [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "hello"}],
        }
    ]


def test_assistant_text_uses_output_text() -> None:
    msgs = [NormalizedMessage(role="assistant", content="ok")]
    out = translate_messages_to_openai(msgs)
    assert out[0]["content"] == [{"type": "output_text", "text": "ok"}]


def test_system_passes_through_top_level() -> None:
    msgs = [NormalizedMessage(role="user", content="hi")]
    out = translate_messages_to_openai(msgs, system="be terse")
    assert out[0]["role"] == "system"
    assert out[0]["content"][0]["text"] == "be terse"
    assert out[1]["role"] == "user"


def test_role_system_message_filtered() -> None:
    """system 在 NormalizedMessage 裡的(舊風格)不該再出現,system 參數會處理。"""
    msgs = [
        NormalizedMessage(role="system", content="will be skipped"),
        NormalizedMessage(role="user", content="x"),
    ]
    out = translate_messages_to_openai(msgs)
    assert all(m["role"] != "system" for m in out)


def test_tool_use_becomes_function_call_item() -> None:
    msgs = [
        NormalizedMessage(
            role="assistant",
            content=[
                TextBlock(text="reading"),
                ToolUseBlock(id="call_1", name="Read", input={"path": "/etc/hosts"}),
            ],
        )
    ]
    out = translate_messages_to_openai(msgs)
    # text 先 flush 為 message,接著 function_call 為獨立 item
    assert out[0]["type"] == "message"
    assert out[0]["content"][0]["type"] == "output_text"
    assert out[1]["type"] == "function_call"
    assert out[1]["call_id"] == "call_1"
    assert out[1]["name"] == "Read"
    assert json.loads(out[1]["arguments"]) == {"path": "/etc/hosts"}


def test_tool_result_becomes_function_call_output() -> None:
    msgs = [
        NormalizedMessage(
            role="user",
            content=[ToolResultBlock(tool_use_id="call_1", content="127.0.0.1 localhost")],
        )
    ]
    out = translate_messages_to_openai(msgs)
    assert out == [
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "127.0.0.1 localhost",
        }
    ]


def test_translate_tools_returns_responses_format() -> None:
    tools = [
        ToolDefinition(
            name="Read",
            description="Read a file",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        )
    ]
    out = translate_tools_to_openai(tools)
    assert out == [
        {
            "type": "function",
            "name": "Read",
            "description": "Read a file",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        }
    ]
