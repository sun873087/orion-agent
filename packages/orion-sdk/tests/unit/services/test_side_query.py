"""side_query — 通用小 LLM 呼叫。Phase 12。"""

from __future__ import annotations

import pytest

from orion_sdk.services.side_query import (
    SideQueryParams,
    side_query,
)
from orion_sdk._testing import MockProvider, MockTurn


@pytest.mark.asyncio
async def test_text_mode_returns_text() -> None:
    """無 schema → 純文字結果。"""
    provider = MockProvider(turns=[MockTurn(text="hello world")])
    result = await side_query(
        SideQueryParams(system="be brief", user_text="say hi"),
        provider=provider,  # type: ignore[arg-type]
    )
    assert result.text == "hello world"
    assert result.structured is None


@pytest.mark.asyncio
async def test_schema_mode_parses_tool_use() -> None:
    """JSON Schema 模式 → 模型 emit tool_use → 解 structured input。"""
    provider = MockProvider(turns=[
        MockTurn(
            tool_uses=[("t1", "respond", {"indices": [2, 0, 5]})],
        ),
    ])
    schema = {
        "name": "respond",
        "schema": {
            "type": "object",
            "properties": {"indices": {"type": "array"}},
            "required": ["indices"],
        },
    }
    result = await side_query(
        SideQueryParams(
            system="rank items",
            user_text="rank these",
            json_schema=schema,
        ),
        provider=provider,  # type: ignore[arg-type]
    )
    assert result.structured == {"indices": [2, 0, 5]}


@pytest.mark.asyncio
async def test_schema_fallback_to_text_json() -> None:
    """provider 不 emit tool_use 但回 JSON 字串 → fallback 解析。"""
    provider = MockProvider(turns=[
        MockTurn(text='{"indices": [1, 3]}'),
    ])
    schema = {
        "name": "respond",
        "schema": {"type": "object"},
    }
    result = await side_query(
        SideQueryParams(
            system="x",
            user_text="y",
            json_schema=schema,
        ),
        provider=provider,  # type: ignore[arg-type]
    )
    assert result.structured == {"indices": [1, 3]}


@pytest.mark.asyncio
async def test_does_not_pollute_provider_call_count() -> None:
    """side_query 內部就一次 provider.stream — captured_calls 應該是 1。"""
    provider = MockProvider(turns=[MockTurn(text="x")])
    await side_query(
        SideQueryParams(system="s", user_text="u"),
        provider=provider,  # type: ignore[arg-type]
    )
    assert len(provider.captured_calls) == 1
    # 沒繼承主 system 段組裝(side_query 預設不接 conversation 主 prompt)
    assert provider.captured_calls[0]["system"] == "s"


@pytest.mark.asyncio
async def test_usage_returned() -> None:
    """MessageStopEvent.usage → SideQueryUsage。"""
    provider = MockProvider(turns=[MockTurn(text="hi")])
    result = await side_query(
        SideQueryParams(system="s", user_text="u"),
        provider=provider,  # type: ignore[arg-type]
    )
    # MockProvider 在 turn 裡硬塞 input_tokens=10, output_tokens=20
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 20


@pytest.mark.asyncio
async def test_invalid_json_text_returns_none_structured() -> None:
    """schema 模式但 model 回亂字 → structured=None,但 text 還是給 caller。"""
    provider = MockProvider(turns=[MockTurn(text="not valid json at all")])
    result = await side_query(
        SideQueryParams(
            system="s",
            user_text="u",
            json_schema={"name": "respond", "schema": {"type": "object"}},
        ),
        provider=provider,  # type: ignore[arg-type]
    )
    assert result.structured is None
    assert result.text == "not valid json at all"


@pytest.mark.asyncio
async def test_text_only_mode_does_not_send_tools() -> None:
    """無 schema → 不送 tools 給 provider(避免模型嘗試呼工具)。"""
    provider = MockProvider(turns=[MockTurn(text="x")])
    await side_query(
        SideQueryParams(system="s", user_text="u"),
        provider=provider,  # type: ignore[arg-type]
    )
    assert provider.captured_calls[0]["tools"] is None


@pytest.mark.asyncio
async def test_schema_mode_sends_one_tool() -> None:
    """schema 模式 → tools 列表只有一個 ToolDefinition,name 同 schema['name']。"""
    provider = MockProvider(turns=[MockTurn(tool_uses=[("t", "respond", {})])])
    await side_query(
        SideQueryParams(
            system="s",
            user_text="u",
            json_schema={"name": "respond", "schema": {"type": "object"}},
        ),
        provider=provider,  # type: ignore[arg-type]
    )
    tools = provider.captured_calls[0]["tools"]
    assert tools is not None
    assert len(tools) == 1
    assert tools[0].name == "respond"
