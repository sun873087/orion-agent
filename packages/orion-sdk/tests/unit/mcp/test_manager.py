"""mcp/manager.py — McpManager(用 mock 不啟真 MCP server)。"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from orion_sdk.mcp.config import StdioMcpConfig
from orion_sdk.mcp.manager import McpManager


class _FakeMcpClient:
    """模擬 McpClient — 不真連 MCP server。"""

    def __init__(
        self,
        server_name: str,
        config: Any,  # noqa: ARG002
        *,
        tools: list[dict] | None = None,
        raise_on_enter: BaseException | None = None,
    ) -> None:
        self.server_name = server_name
        self._tools = tools or []
        self._raise = raise_on_enter
        self.entered = False

    async def __aenter__(self) -> _FakeMcpClient:
        if self._raise:
            raise self._raise
        self.entered = True
        return self

    async def __aexit__(self, *args: object) -> None:
        self.entered = False

    async def list_tools(self) -> list[dict]:
        return list(self._tools)


@pytest.mark.asyncio
async def test_manager_with_no_configs() -> None:
    """無 servers → enter 後 tools = []。"""
    async with McpManager(configs={}) as mgr:
        assert mgr.tools == []
        assert mgr.connected_servers == []


@pytest.mark.asyncio
async def test_manager_loads_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """單一 server,wrap_mcp_tool 應產生 mcp__<srv>__<tool> 名稱。"""
    fake_client = _FakeMcpClient(
        "srv",
        None,
        tools=[
            {"name": "list_files", "description": "list", "inputSchema": {"type": "object"}},
            {"name": "read_file", "description": "read", "inputSchema": {"type": "object"}},
        ],
    )

    def _stub_client(name: str, config: Any) -> _FakeMcpClient:  # noqa: ARG001
        return fake_client

    monkeypatch.setattr("orion_sdk.mcp.manager.McpClient", _stub_client)

    configs = {"srv": StdioMcpConfig(command="echo")}
    async with McpManager(configs=configs) as mgr:
        names = sorted(t.name for t in mgr.tools)
        assert names == ["mcp__srv__list_files", "mcp__srv__read_file"]
        assert mgr.connected_servers == ["srv"]


@pytest.mark.asyncio
async def test_manager_failure_does_not_block_others(monkeypatch: pytest.MonkeyPatch) -> None:
    """server A 連線失敗 → server B 仍正常。"""
    def _stub_client(name: str, config: Any) -> _FakeMcpClient:  # noqa: ARG001
        if name == "broken":
            return _FakeMcpClient(name, config, raise_on_enter=RuntimeError("connection refused"))
        return _FakeMcpClient(
            name, config,
            tools=[{"name": "ok", "description": "ok", "inputSchema": {"type": "object"}}],
        )

    monkeypatch.setattr("orion_sdk.mcp.manager.McpClient", _stub_client)

    configs = {
        "broken": StdioMcpConfig(command="x"),
        "good": StdioMcpConfig(command="y"),
    }
    async with McpManager(configs=configs) as mgr:
        assert mgr.connected_servers == ["good"]
        assert "broken" in mgr.connection_errors
        assert "connection refused" in mgr.connection_errors["broken"]
        names = [t.name for t in mgr.tools]
        assert names == ["mcp__good__ok"]


@pytest.mark.asyncio
async def test_server_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    def _stub_client(name: str, config: Any) -> _FakeMcpClient:  # noqa: ARG001
        return _FakeMcpClient(
            name, config,
            tools=[
                {"name": "t1", "description": "t1", "inputSchema": {"type": "object"}},
                {"name": "t2", "description": "t2", "inputSchema": {"type": "object"}},
            ],
        )

    monkeypatch.setattr("orion_sdk.mcp.manager.McpClient", _stub_client)

    configs = {"fs": StdioMcpConfig(command="x")}
    async with McpManager(configs=configs) as mgr:
        summary = mgr.server_summary()
        assert "**fs**" in summary
        assert "2 tools" in summary


_ = AsyncMock  # keep import to avoid lint
_ = patch
