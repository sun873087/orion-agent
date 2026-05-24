"""OpenRouter provider — smoke + translation unit tests。

不打真實 OpenRouter HTTP — 走 monkeypatch / fake client。
"""

from __future__ import annotations

import json

import pytest

from orion_model.openrouter_provider import (
    OpenRouterProvider,
    _map_stop_reason,
    _translate_messages_to_chat_completions,
    _translate_tools_to_chat_completions,
)
from orion_model.tool_def import ToolDefinition
from orion_model.types import (
    ImageBlock,
    NormalizedMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)


# ─── Provider basics(對 models.json 內 static 模型驗) ──────────────


def test_provider_name() -> None:
    """name attribute 必須是 'openrouter'(get_provider 用這 dispatch)。"""
    assert OpenRouterProvider.name == "openrouter"


def test_provider_instantiation_uses_static_catalog() -> None:
    """建構走 models.json static catalog,不打網路。"""
    provider = OpenRouterProvider(model="deepseek/deepseek-v4-flash:free")
    assert provider.model == "deepseek/deepseek-v4-flash:free"
    assert provider.capabilities.max_context_tokens == 163840
    assert provider.capabilities.parallel_tool_calls is True


def test_provider_unknown_model_falls_back_to_default_context() -> None:
    """不在 models.json 的 model → max_context_tokens fallback default。"""
    provider = OpenRouterProvider(model="random/ghost-model")
    assert provider.capabilities.max_context_tokens == 128_000 # _DEFAULT_CONTEXT_TOKENS


def test_cost_static_model_free_tier_is_zero() -> None:
    """static :free model pricing 全 0 → cost 0。"""
    p = OpenRouterProvider(model="openai/gpt-oss-120b:free")
    cost = p.estimate_cost(input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == 0.0


def test_cost_unknown_model_uses_fallback_zero() -> None:
    """models.json 沒登錄的 model → pricing.get_pricing fallback 機制(unknown
    provider+model 沒 fallback 對應就回 zero)。"""
    p = OpenRouterProvider(model="ghost/model")
    cost = p.estimate_cost(input_tokens=10_000_000, output_tokens=10_000_000)
    # openrouter 沒進 _FALLBACK_BY_PROVIDER,catalog 也找不到 → 全 0
    assert cost == 0.0


# ─── _map_stop_reason ──────────────────────────────────────────


def test_map_stop_reason() -> None:
    assert _map_stop_reason("stop") == "end_turn"
    assert _map_stop_reason("length") == "max_tokens"
    assert _map_stop_reason("tool_calls") == "tool_use"
    assert _map_stop_reason("content_filter") == "content_filter"
    assert _map_stop_reason(None) == "end_turn"
    assert _map_stop_reason("weird") == "end_turn"


# ─── _translate_messages_to_chat_completions ─────────────────────


def test_translate_simple_user_assistant() -> None:
    msgs = [
        NormalizedMessage(role="user", content="hi"),
        NormalizedMessage(role="assistant", content="hello"),
    ]
    out = _translate_messages_to_chat_completions(msgs, system="you are helpful")
    assert out == [
        {"role": "system", "content": "you are helpful"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


def test_translate_no_system_omits_system_msg() -> None:
    out = _translate_messages_to_chat_completions(
        [NormalizedMessage(role="user", content="x")], system="",
    )
    assert out[0]["role"] == "user"


def test_translate_image_block() -> None:
    msg = NormalizedMessage(
        role="user",
        content=[
            TextBlock(text="describe this"),
            ImageBlock(media_type="image/png", data="ABC123"),
        ],
    )
    out = _translate_messages_to_chat_completions([msg], system="")
    assert len(out) == 1
    content = out[0]["content"]
    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "describe this"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"] == "data:image/png;base64,ABC123"


def test_translate_tool_use_in_assistant() -> None:
    msg = NormalizedMessage(
        role="assistant",
        content=[
            TextBlock(text="I'll search."),
            ToolUseBlock(id="tu_1", name="Search", input={"q": "weather"}),
        ],
    )
    out = _translate_messages_to_chat_completions([msg], system="")
    assert len(out) == 1
    asst = out[0]
    assert asst["role"] == "assistant"
    assert asst["content"] == "I'll search."
    assert len(asst["tool_calls"]) == 1
    tc = asst["tool_calls"][0]
    assert tc["id"] == "tu_1"
    assert tc["type"] == "function"
    assert tc["function"]["name"] == "Search"
    assert json.loads(tc["function"]["arguments"]) == {"q": "weather"}


def test_translate_tool_result_splits_into_tool_role() -> None:
    """user msg with tool_result blocks → 拆成 role='tool' messages。"""
    msg = NormalizedMessage(
        role="user",
        content=[
            ToolResultBlock(tool_use_id="tu_1", content="sunny"),
            ToolResultBlock(tool_use_id="tu_2", content="cloudy"),
        ],
    )
    out = _translate_messages_to_chat_completions([msg], system="")
    assert len(out) == 2
    assert out[0] == {"role": "tool", "tool_call_id": "tu_1", "content": "sunny"}
    assert out[1] == {"role": "tool", "tool_call_id": "tu_2", "content": "cloudy"}


def test_translate_mixed_user_text_image_tool_result() -> None:
    """User msg 帶 text + image + tool_result → text/image 一條,tool_result 另外拆。"""
    msg = NormalizedMessage(
        role="user",
        content=[
            TextBlock(text="follow-up:"),
            ImageBlock(media_type="image/jpeg", data="IMG"),
            ToolResultBlock(tool_use_id="tu_x", content="prior result"),
        ],
    )
    out = _translate_messages_to_chat_completions([msg], system="")
    # 第一條:user with text + image(list);第二條:tool role
    assert len(out) == 2
    assert out[0]["role"] == "user"
    assert isinstance(out[0]["content"], list)
    assert out[1]["role"] == "tool"
    assert out[1]["tool_call_id"] == "tu_x"


def test_translate_tools_format() -> None:
    tools = [
        ToolDefinition(
            name="Search",
            description="Search the web",
            input_schema={"type": "object", "properties": {"q": {"type": "string"}}},
        ),
    ]
    out = _translate_tools_to_chat_completions(tools)
    assert out == [
        {
            "type": "function",
            "function": {
                "name": "Search",
                "description": "Search the web",
                "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
            },
        },
    ]


def test_translate_empty_tools() -> None:
    assert _translate_tools_to_chat_completions([]) == []
