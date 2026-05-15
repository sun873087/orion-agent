"""Transport 啟動 helper — 包 mcp SDK 的 stdio / http connect 邏輯。

對應 spec § 5 transports.py。

Phase 5 範圍:
- stdio:本機 subprocess(主流)
- http:遠端 HTTP(透過 mcp SDK,Phase 5 範圍只 stub 待測)

SSE / InProcess 留 Phase 5b。

每個 connect_* function 回 (read_stream, write_stream) 給 ClientSession 用。
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Any

from orion_sdk.mcp.config import HttpMcpConfig, McpServerConfig, StdioMcpConfig


def open_transport(
    config: McpServerConfig,
) -> AbstractAsyncContextManager[tuple[Any, Any]]:
    """根據 config type 回 async context manager,yield (read, write) streams。

    Caller 用法:
        async with open_transport(config) as (read, write):
            async with ClientSession(read, write) as session:
                ...
    """
    if isinstance(config, StdioMcpConfig):
        return _open_stdio(config)
    if isinstance(config, HttpMcpConfig):
        return _open_http(config)
    raise ValueError(f"Unknown MCP transport type: {type(config).__name__}")


def _open_stdio(config: StdioMcpConfig) -> AbstractAsyncContextManager[tuple[Any, Any]]:
    """delegate to mcp SDK 的 stdio_client。"""
    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=config.command,
        args=list(config.args),
        env=config.env,
    )
    return stdio_client(params)


def _open_http(config: HttpMcpConfig) -> AbstractAsyncContextManager[tuple[Any, Any]]:
    """HTTP transport — Phase 5 stub。

    TODO Phase 5b:接 mcp.client.streamable_http.streamablehttp_client。
    """
    raise NotImplementedError(
        f"HTTP MCP transport for {config.url!r} not implemented in Phase 5; "
        "see Phase 5b roadmap"
    )
