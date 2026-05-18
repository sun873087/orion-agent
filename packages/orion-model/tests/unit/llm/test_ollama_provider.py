"""OllamaProvider stream test — mock NDJSON via httpx.MockTransport。"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from orion_model.events import (
    MessageStartEvent,
    MessageStopEvent,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ToolUseStartEvent,
    ToolUseStopEvent,
)
from orion_model.ollama_provider import OllamaProvider, resolve_ollama_base_url
from orion_model.tool_def import ToolDefinition
from orion_model.types import NormalizedMessage


def _mock_client(ndjson_lines: list[dict[str, Any]]) -> httpx.AsyncClient:
    """建一個回傳 NDJSON streaming response 的 mock httpx client。"""

    def handler(request: httpx.Request) -> httpx.Response:
        body = "\n".join(json.dumps(line) for line in ndjson_lines) + "\n"
        return httpx.Response(200, content=body.encode("utf-8"))

    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport)


# ─── Basic streaming ────────────────────────────────────────────────


async def test_text_only_streaming() -> None:
    """簡單 text response → TextDeltaEvent stream + final MessageStopEvent。"""
    lines = [
        {"model": "test", "message": {"role": "assistant", "content": "Hello"}, "done": False},
        {"model": "test", "message": {"role": "assistant", "content": " world"}, "done": False},
        {
            "model": "test",
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 10,
            "eval_count": 5,
        },
    ]
    client = _mock_client(lines)
    provider = OllamaProvider(model="test", client=client)
    events = []
    async for ev in provider.stream(
        system="be terse",
        messages=[NormalizedMessage(role="user", content="hi")],
    ):
        events.append(ev)
    await client.aclose()

    # 預期:MessageStart, TextDelta("Hello"), TextDelta(" world"), MessageStop
    assert isinstance(events[0], MessageStartEvent)
    text_events = [e for e in events if isinstance(e, TextDeltaEvent)]
    assert [e.text for e in text_events] == ["Hello", " world"]
    stop = events[-1]
    assert isinstance(stop, MessageStopEvent)
    assert stop.usage.input_tokens == 10
    assert stop.usage.output_tokens == 5
    assert stop.stop_reason == "end_turn"


async def test_tool_call_streaming() -> None:
    """Tool call in last NDJSON → ToolUseStart + Delta + Stop + MessageStop(tool_use)。"""
    lines = [
        {"model": "test", "message": {"role": "assistant", "content": "Let me check"}, "done": False},
        {
            "model": "test",
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "Read",
                            "arguments": {"path": "/etc/hosts"},
                        }
                    }
                ],
            },
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 20,
            "eval_count": 8,
        },
    ]
    client = _mock_client(lines)
    provider = OllamaProvider(model="test", client=client)
    events = []
    async for ev in provider.stream(
        system="",
        messages=[NormalizedMessage(role="user", content="read /etc/hosts")],
        tools=[
            ToolDefinition(
                name="Read",
                description="read",
                input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
            )
        ],
    ):
        events.append(ev)
    await client.aclose()

    tool_starts = [e for e in events if isinstance(e, ToolUseStartEvent)]
    tool_stops = [e for e in events if isinstance(e, ToolUseStopEvent)]
    assert len(tool_starts) == 1
    assert tool_starts[0].tool_name == "Read"
    assert len(tool_stops) == 1
    assert tool_stops[0].full_input == {"path": "/etc/hosts"}
    stop = events[-1]
    assert isinstance(stop, MessageStopEvent)
    assert stop.stop_reason == "tool_use"


async def test_thinking_inline_split() -> None:
    """`<think>...</think>` inline content → split 出 ThinkingDelta + TextDelta。"""
    lines = [
        {
            "model": "test",
            "message": {"role": "assistant", "content": "<think>reasoning</think> answer"},
            "done": False,
        },
        {
            "model": "test",
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 5,
            "eval_count": 3,
        },
    ]
    client = _mock_client(lines)
    provider = OllamaProvider(model="test", client=client)
    events = []
    async for ev in provider.stream(system="", messages=[NormalizedMessage(role="user", content="q")]):
        events.append(ev)
    await client.aclose()

    thinking = [e for e in events if isinstance(e, ThinkingDeltaEvent)]
    text = [e for e in events if isinstance(e, TextDeltaEvent)]
    assert [e.text for e in thinking] == ["reasoning"]
    assert [e.text for e in text] == [" answer"]


async def test_length_done_reason_maps_max_tokens() -> None:
    lines = [
        {"model": "test", "message": {"role": "assistant", "content": "very long..."}, "done": False},
        {
            "model": "test",
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "done_reason": "length",
            "prompt_eval_count": 1,
            "eval_count": 100,
        },
    ]
    client = _mock_client(lines)
    provider = OllamaProvider(model="test", client=client)
    stop = None
    async for ev in provider.stream(system="", messages=[NormalizedMessage(role="user", content="q")]):
        if isinstance(ev, MessageStopEvent):
            stop = ev
    await client.aclose()
    assert stop is not None
    assert stop.stop_reason == "max_tokens"


# ─── Error handling ─────────────────────────────────────────────────


async def test_connect_error_raises_friendly_message() -> None:
    """Ollama 沒開時 connect refused → 友善 error,提示 `ollama serve`。"""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    provider = OllamaProvider(model="test", client=client)
    with pytest.raises(RuntimeError, match="ollama serve"):
        async for _ in provider.stream(
            system="", messages=[NormalizedMessage(role="user", content="q")]
        ):
            pass
    await client.aclose()


# ─── Misc ────────────────────────────────────────────────────────────


def test_estimate_cost_zero_for_local() -> None:
    provider = OllamaProvider(model="any")
    assert provider.estimate_cost(input_tokens=1000, output_tokens=500) == 0.0


def test_resolve_base_url_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    # explicit override 最高
    monkeypatch.setenv("OLLAMA_HOST", "env-host:1111")
    assert resolve_ollama_base_url("http://override:9999") == "http://override:9999"
    # env 沒 scheme 自動補
    monkeypatch.setenv("OLLAMA_HOST", "env-host:1111")
    assert resolve_ollama_base_url() == "http://env-host:1111"
    # env 完整 URL passthrough
    monkeypatch.setenv("OLLAMA_HOST", "https://remote.example/")
    assert resolve_ollama_base_url() == "https://remote.example"
    # 沒 env 沒 override → 預設
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    assert resolve_ollama_base_url() == "http://localhost:11434"
