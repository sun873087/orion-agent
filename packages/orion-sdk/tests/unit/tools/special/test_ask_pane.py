"""AskPaneTool — unit tests。

驗證:
- callback 沒 inject → ErrorEvent
- callback 注入 → 回 transcript_excerpt + status
- ctx.session_id 沒 set → ErrorEvent
- not_found 狀態 → hint 訊息
- callback raise → ErrorEvent + 訊息含 exception type
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent
from orion_sdk.tools.special import AskPaneInput, AskPaneTool


@pytest.fixture
def ctx() -> AgentContext:
    return AgentContext(session_id=uuid4())


@pytest.mark.asyncio
async def test_no_callback_yields_error(ctx):
    tool = AskPaneTool() # no callback
    events = [e async for e in tool.call(AskPaneInput(pane_name="@x"), ctx)]
    assert len(events) == 1
    assert isinstance(events[0], ErrorEvent)
    assert "not wired" in events[0].message


@pytest.mark.asyncio
async def test_callback_returns_done_status(ctx):
    async def cb(params):
        assert params["pane_name"] == "@reviewer"
        assert params["requesting_session_id"] == str(ctx.session_id)
        return {
            "status": "done",
            "pane_name": "@reviewer",
            "pane_role": "reviewer",
            "transcript_excerpt": [
                {"role": "user", "text": "review please"},
                {"role": "assistant", "text": "LGTM"},
            ],
            "partial_output": None,
        }

    tool = AskPaneTool(callback=cb)
    events = [e async for e in tool.call(AskPaneInput(pane_name="@reviewer"), ctx)]
    assert len(events) == 1
    ev = events[0]
    assert isinstance(ev, TextEvent)
    data = json.loads(ev.text)
    assert data["status"] == "done"
    assert data["pane_role"] == "reviewer"
    assert len(data["transcript_excerpt"]) == 2


@pytest.mark.asyncio
async def test_callback_returns_running_status_with_partial(ctx):
    async def cb(_params):
        return {
            "status": "running",
            "pane_name": "@coder",
            "current_action": "streaming response...",
            "transcript_excerpt": [{"role": "user", "text": "implement X"}],
            "partial_output": "Looking at the existing impl...",
        }

    tool = AskPaneTool(callback=cb)
    events = [e async for e in tool.call(AskPaneInput(pane_name="@coder"), ctx)]
    data = json.loads(events[0].text)
    assert data["status"] == "running"
    assert data["partial_output"].startswith("Looking at")
    assert data["current_action"] == "streaming response..."


@pytest.mark.asyncio
async def test_callback_returns_not_found(ctx):
    async def cb(_params):
        return {"status": "not_found", "pane_name": "@ghost"}

    tool = AskPaneTool(callback=cb)
    events = [e async for e in tool.call(AskPaneInput(pane_name="@ghost"), ctx)]
    data = json.loads(events[0].text)
    assert data["status"] == "not_found"
    assert "hint" in data


@pytest.mark.asyncio
async def test_callback_raises_yields_error(ctx):
    async def cb(_params):
        raise RuntimeError("DB down")

    tool = AskPaneTool(callback=cb)
    events = [e async for e in tool.call(AskPaneInput(pane_name="@x"), ctx)]
    assert isinstance(events[0], ErrorEvent)
    assert "RuntimeError" in events[0].message
    assert "DB down" in events[0].message


@pytest.mark.asyncio
async def test_callback_raises_value_error_propagates_message_only(ctx):
    """ValueError 被當 user-visible 訊息直接 surface(不含 exception type 前綴)。"""
    async def cb(_params):
        raise ValueError("invalid pane name format")

    tool = AskPaneTool(callback=cb)
    events = [e async for e in tool.call(AskPaneInput(pane_name="@x"), ctx)]
    assert isinstance(events[0], ErrorEvent)
    assert events[0].message == "invalid pane name format"


@pytest.mark.asyncio
async def test_tool_is_read_only_and_concurrency_safe(ctx):
    tool = AskPaneTool(callback=None)
    inp = AskPaneInput(pane_name="@x")
    assert tool.is_read_only(inp) is True
    assert tool.is_concurrency_safe(inp) is True


@pytest.mark.asyncio
async def test_callback_returns_malformed_payload(ctx):
    async def cb(_params):
        return "not a dict" # type: ignore[return-value]

    tool = AskPaneTool(callback=cb)
    events = [e async for e in tool.call(AskPaneInput(pane_name="@x"), ctx)]
    assert isinstance(events[0], ErrorEvent)
    assert "malformed" in events[0].message


def test_input_validation_n_recent_clamped():
    # ge=1, le=50
    with pytest.raises(Exception):
        AskPaneInput(pane_name="@x", n_recent_messages=0)
    with pytest.raises(Exception):
        AskPaneInput(pane_name="@x", n_recent_messages=51)
    # default 8
    inp = AskPaneInput(pane_name="@x")
    assert inp.n_recent_messages == 8


def test_input_validation_pane_name_length():
    with pytest.raises(Exception):
        AskPaneInput(pane_name="")
    with pytest.raises(Exception):
        AskPaneInput(pane_name="x" * 129)
