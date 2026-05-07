"""mcp/tool_wrapper.py — wrap_mcp_tool 行為。"""

from __future__ import annotations

from typing import Any

import pytest

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import ErrorEvent, TextEvent, Tool
from orion_agent.mcp.tool_wrapper import wrap_mcp_tool


class _StubClient:
    """假 McpClient — call_tool 回 scripted result。"""

    def __init__(self, *, response: dict[str, Any] | None = None,
                 raise_exc: BaseException | None = None) -> None:
        self.response = response
        self.raise_exc = raise_exc
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, args))
        if self.raise_exc:
            raise self.raise_exc
        return self.response or {"isError": False, "content": []}


def test_wrap_naming() -> None:
    tool_def = {
        "name": "read_file",
        "description": "Read a file",
        "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    }
    wrapper = wrap_mcp_tool(server_name="fs", tool_def=tool_def, client=_StubClient())  # type: ignore[arg-type]
    assert wrapper.name == "mcp__fs__read_file"
    assert "Read a file" in wrapper.description


def test_annotations_drive_concurrency_safety() -> None:
    tool_def = {
        "name": "list",
        "description": "list dir",
        "inputSchema": {"type": "object"},
        "annotations": {"readOnlyHint": True},
    }
    wrapper = wrap_mcp_tool(server_name="fs", tool_def=tool_def, client=_StubClient())  # type: ignore[arg-type]
    assert wrapper.is_concurrency_safe(None) is True
    assert wrapper.is_read_only(None) is True


def test_destructive_overrides_safe() -> None:
    tool_def = {
        "name": "delete",
        "description": "delete file",
        "inputSchema": {"type": "object"},
        "annotations": {"destructiveHint": True, "readOnlyHint": True},
    }
    wrapper = wrap_mcp_tool(server_name="fs", tool_def=tool_def, client=_StubClient())  # type: ignore[arg-type]
    # destructive=True → not concurrency safe(safety overrides read-only)
    assert wrapper.is_concurrency_safe(None) is False


def test_no_annotations_conservative() -> None:
    tool_def = {"name": "x", "description": "x", "inputSchema": {"type": "object"}}
    wrapper = wrap_mcp_tool(server_name="srv", tool_def=tool_def, client=_StubClient())  # type: ignore[arg-type]
    assert wrapper.is_concurrency_safe(None) is False
    assert wrapper.is_read_only(None) is False


def test_protocol_compliance() -> None:
    """McpToolWrapper 應符合 Tool Protocol(runtime_checkable)。"""
    tool_def = {"name": "x", "description": "x", "inputSchema": {"type": "object"}}
    wrapper = wrap_mcp_tool(server_name="s", tool_def=tool_def, client=_StubClient())  # type: ignore[arg-type]
    assert isinstance(wrapper, Tool)


@pytest.mark.asyncio
async def test_call_returns_text_from_content() -> None:
    client = _StubClient(response={
        "isError": False,
        "content": [{"type": "text", "text": "hello world"}],
    })
    tool_def = {
        "name": "echo", "description": "x",
        "inputSchema": {"type": "object", "properties": {"msg": {"type": "string"}}, "required": ["msg"]},
    }
    wrapper = wrap_mcp_tool(server_name="srv", tool_def=tool_def, client=client)  # type: ignore[arg-type]

    input_obj = wrapper.input_schema(msg="x")
    events = [e async for e in wrapper.call(input_obj, AgentContext())]
    assert len(events) == 1
    assert isinstance(events[0], TextEvent)
    assert events[0].text == "hello world"
    # 原 args 應傳給 client
    assert client.calls == [("echo", {"msg": "x"})]


@pytest.mark.asyncio
async def test_call_isError_yields_error_event() -> None:
    client = _StubClient(response={
        "isError": True,
        "content": [{"type": "text", "text": "perm denied"}],
    })
    tool_def = {"name": "x", "description": "x", "inputSchema": {"type": "object"}}
    wrapper = wrap_mcp_tool(server_name="srv", tool_def=tool_def, client=client)  # type: ignore[arg-type]
    events = [e async for e in wrapper.call(wrapper.input_schema(), AgentContext())]
    assert isinstance(events[0], ErrorEvent)
    assert "perm denied" in events[0].message


@pytest.mark.asyncio
async def test_call_exception_caught() -> None:
    client = _StubClient(raise_exc=RuntimeError("boom"))
    tool_def = {"name": "x", "description": "x", "inputSchema": {"type": "object"}}
    wrapper = wrap_mcp_tool(server_name="srv", tool_def=tool_def, client=client)  # type: ignore[arg-type]
    events = [e async for e in wrapper.call(wrapper.input_schema(), AgentContext())]
    assert isinstance(events[0], ErrorEvent)
    assert "boom" in events[0].message


@pytest.mark.asyncio
async def test_call_image_content_elided() -> None:
    client = _StubClient(response={
        "isError": False,
        "content": [
            {"type": "text", "text": "intro"},
            {"type": "image", "data": "..."},
        ],
    })
    tool_def = {"name": "x", "description": "x", "inputSchema": {"type": "object"}}
    wrapper = wrap_mcp_tool(server_name="srv", tool_def=tool_def, client=client)  # type: ignore[arg-type]
    events = [e async for e in wrapper.call(wrapper.input_schema(), AgentContext())]
    assert isinstance(events[0], TextEvent)
    assert "intro" in events[0].text
    assert "image content elided" in events[0].text
