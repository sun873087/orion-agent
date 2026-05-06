"""Normalized → Anthropic 翻譯。"""

from __future__ import annotations

from orion_agent.llm.tool_def import ToolDefinition
from orion_agent.llm.translation.anthropic import (
    apply_cache_breakpoints,
    translate_messages_to_anthropic,
    translate_tools_to_anthropic,
)
from orion_agent.llm.types import (
    NormalizedMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)


def test_simple_text_message() -> None:
    msgs = [NormalizedMessage(role="user", content="hello")]
    out = translate_messages_to_anthropic(msgs)
    assert out == [{"role": "user", "content": "hello"}]


def test_system_message_filtered() -> None:
    msgs = [
        NormalizedMessage(role="system", content="ignored"),
        NormalizedMessage(role="user", content="hi"),
    ]
    out = translate_messages_to_anthropic(msgs)
    assert len(out) == 1
    assert out[0]["role"] == "user"


def test_tool_use_and_result_blocks() -> None:
    msgs = [
        NormalizedMessage(
            role="assistant",
            content=[
                TextBlock(text="reading file"),
                ToolUseBlock(id="tu_1", name="Read", input={"path": "/etc/hosts"}),
            ],
        ),
        NormalizedMessage(
            role="user",
            content=[
                ToolResultBlock(tool_use_id="tu_1", content="127.0.0.1 localhost"),
            ],
        ),
    ]
    out = translate_messages_to_anthropic(msgs)
    assert out[0]["role"] == "assistant"
    blocks = out[0]["content"]
    assert blocks[0] == {"type": "text", "text": "reading file"}
    assert blocks[1]["type"] == "tool_use"
    assert blocks[1]["id"] == "tu_1"
    assert out[1]["content"][0]["type"] == "tool_result"
    assert out[1]["content"][0]["tool_use_id"] == "tu_1"


def test_translate_tools_basic() -> None:
    tools = [
        ToolDefinition(
            name="Read",
            description="Read a file",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        )
    ]
    out = translate_tools_to_anthropic(tools)
    assert out == [
        {
            "name": "Read",
            "description": "Read a file",
            "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
        }
    ]


def test_translate_tools_with_cache_control() -> None:
    tools = [
        ToolDefinition(
            name="Read",
            description="x",
            input_schema={"type": "object"},
            cache_control=True,
        )
    ]
    out = translate_tools_to_anthropic(tools)
    assert out[0]["cache_control"] == {"type": "ephemeral"}


def test_apply_cache_breakpoints_marks_last_block() -> None:
    msgs = [
        {"role": "user", "content": [{"type": "text", "text": "first"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "reply"}]},
    ]
    out = apply_cache_breakpoints(msgs, [0])
    assert out[0]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    # 第二則沒被標
    assert "cache_control" not in out[1]["content"][-1]


def test_apply_cache_breakpoints_out_of_range_noop() -> None:
    msgs = [{"role": "user", "content": [{"type": "text", "text": "x"}]}]
    out = apply_cache_breakpoints(msgs, [99])
    assert "cache_control" not in out[0]["content"][-1]
