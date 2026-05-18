"""Normalized → Ollama `/api/chat` 翻譯。"""

from __future__ import annotations

from orion_model.tool_def import ToolDefinition
from orion_model.translation.ollama import (
    split_thinking_from_content,
    translate_messages_to_ollama,
    translate_tools_to_ollama,
)
from orion_model.types import (
    ImageBlock,
    NormalizedMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)


# ─── translate_messages_to_ollama ────────────────────────────────────


def test_user_text_passthrough() -> None:
    msgs = [NormalizedMessage(role="user", content="hello")]
    out = translate_messages_to_ollama(msgs)
    assert out == [{"role": "user", "content": "hello"}]


def test_assistant_text_passthrough() -> None:
    msgs = [NormalizedMessage(role="assistant", content="ok")]
    out = translate_messages_to_ollama(msgs)
    assert out == [{"role": "assistant", "content": "ok"}]


def test_system_prepended() -> None:
    msgs = [NormalizedMessage(role="user", content="hi")]
    out = translate_messages_to_ollama(msgs, system="be terse")
    assert out[0] == {"role": "system", "content": "be terse"}
    assert out[1] == {"role": "user", "content": "hi"}


def test_system_role_in_messages_skipped() -> None:
    """role=system messages 已由 system 參數處理,不重複。"""
    msgs = [
        NormalizedMessage(role="system", content="ignored"),
        NormalizedMessage(role="user", content="hi"),
    ]
    out = translate_messages_to_ollama(msgs, system="real system")
    assert len(out) == 2
    assert out[0]["role"] == "system" and out[0]["content"] == "real system"
    assert out[1]["role"] == "user"


def test_image_block_goes_to_images_array() -> None:
    """Ollama image:base64 string 進 `images` array,不是 content list。"""
    msgs = [
        NormalizedMessage(
            role="user",
            content=[
                TextBlock(text="describe"),
                ImageBlock(media_type="image/png", data="BASE64_DATA"),
            ],
        )
    ]
    out = translate_messages_to_ollama(msgs)
    assert out == [{"role": "user", "content": "describe", "images": ["BASE64_DATA"]}]


def test_tool_use_block_becomes_tool_calls() -> None:
    """ToolUseBlock → assistant message 的 tool_calls(arguments 是 dict 不是 string)。"""
    msgs = [
        NormalizedMessage(
            role="assistant",
            content=[
                TextBlock(text="calling tool"),
                ToolUseBlock(id="call_1", name="Read", input={"path": "/tmp/x"}),
            ],
        )
    ]
    out = translate_messages_to_ollama(msgs)
    assert out[0]["role"] == "assistant"
    assert out[0]["content"] == "calling tool"
    assert out[0]["tool_calls"] == [
        {"function": {"name": "Read", "arguments": {"path": "/tmp/x"}}}
    ]


def test_tool_result_becomes_role_tool() -> None:
    """ToolResultBlock → 獨立的 {role:tool, content:str} message(Ollama 按順序對應)。"""
    msgs = [
        NormalizedMessage(
            role="user",
            content=[
                ToolResultBlock(tool_use_id="call_1", content="file contents", is_error=False),
            ],
        )
    ]
    out = translate_messages_to_ollama(msgs)
    assert out == [{"role": "tool", "content": "file contents"}]


def test_tool_result_with_error_prefixed() -> None:
    msgs = [
        NormalizedMessage(
            role="user",
            content=[
                ToolResultBlock(tool_use_id="x", content="boom", is_error=True),
            ],
        )
    ]
    out = translate_messages_to_ollama(msgs)
    assert out[0]["content"] == "[error] boom"


# ─── translate_tools_to_ollama ───────────────────────────────────────


def test_tool_def_uses_function_wrapper() -> None:
    """Ollama tools schema 包一層 `function`(對齊 OpenAI chat.completions)。"""
    tools = [
        ToolDefinition(
            name="Read",
            description="Read a file",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        )
    ]
    out = translate_tools_to_ollama(tools)
    assert out == [
        {
            "type": "function",
            "function": {
                "name": "Read",
                "description": "Read a file",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            },
        }
    ]


# ─── split_thinking_from_content(DeepSeek-R1 inline `<think>...</think>`)─


def test_split_thinking_simple() -> None:
    parts, in_thinking = split_thinking_from_content(
        "hello <think>reasoning</think> world", in_thinking=False
    )
    assert parts == [
        ("text", "hello "),
        ("thinking", "reasoning"),
        ("text", " world"),
    ]
    assert in_thinking is False


def test_split_thinking_continuation_across_chunks() -> None:
    """模型可能在多 NDJSON 行內 emit `<think>` block — caller 維護 in_thinking 跨行。"""
    # 第一行:開了 <think> 但沒關
    parts1, state1 = split_thinking_from_content("a <think>step 1", in_thinking=False)
    assert parts1 == [("text", "a "), ("thinking", "step 1")]
    assert state1 is True

    # 第二行:延續 thinking,然後關閉,進文字
    parts2, state2 = split_thinking_from_content(" step 2</think> final", in_thinking=True)
    assert parts2 == [
        ("thinking", " step 2"),
        ("text", " final"),
    ]
    assert state2 is False


def test_split_thinking_plain_text() -> None:
    parts, in_thinking = split_thinking_from_content("no tags here", in_thinking=False)
    assert parts == [("text", "no tags here")]
    assert in_thinking is False
