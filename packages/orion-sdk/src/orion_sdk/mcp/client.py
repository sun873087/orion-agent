"""McpClient — 跟單一 MCP server 的連線 + lifecycle 管理。

對應 spec § 5 client.py。

設計:
- async context manager (async with McpClient(config) as client:)
- 進去 connect → list_tools 一次列舉
- call_tool 可重複呼
- 出 context 自動 cleanup(關 session、kill subprocess)

McpManager 把多個 McpClient 集中管理(用 AsyncExitStack)。
"""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from types import TracebackType
from typing import Any

from orion_sdk.mcp.config import McpServerConfig
from orion_sdk.mcp.transports import open_transport

logger = logging.getLogger(__name__)


class McpClient:
    """單一 MCP server connection。"""

    def __init__(self, server_name: str, config: McpServerConfig) -> None:
        self.server_name = server_name
        self.config = config
        self._exit_stack: AsyncExitStack | None = None
        self._session: Any = None  # mcp.ClientSession,延遲 import 避免 hard dep
        self._tools_cache: list[dict[str, Any]] | None = None

    async def __aenter__(self) -> McpClient:
        from mcp import ClientSession

        self._exit_stack = AsyncExitStack()
        try:
            transport_cm = open_transport(self.config)
            read_stream, write_stream = await self._exit_stack.enter_async_context(
                transport_cm,
            )
            self._session = await self._exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream),
            )
            await self._session.initialize()
        except Exception:
            await self._exit_stack.aclose()
            self._exit_stack = None
            self._session = None
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._exit_stack is not None:
            try:
                await self._exit_stack.aclose()
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "MCP server %r cleanup raised: %s", self.server_name, e,
                )
        self._exit_stack = None
        self._session = None

    async def list_tools(self) -> list[dict[str, Any]]:
        """列舉 server 提供的 tools。回 list of dict(name / description / inputSchema / annotations)。"""
        if self._tools_cache is not None:
            return self._tools_cache
        if self._session is None:
            raise RuntimeError("McpClient not entered (use async with)")

        result = await self._session.list_tools()
        # mcp SDK ListToolsResult.tools: list[Tool]
        out: list[dict[str, Any]] = []
        for t in getattr(result, "tools", []):
            tool_dict = {
                "name": getattr(t, "name", ""),
                "description": getattr(t, "description", "") or "",
                "inputSchema": getattr(t, "inputSchema", {}) or {},
            }
            annotations = getattr(t, "annotations", None)
            if annotations is not None:
                # annotations 通常是 Pydantic BaseModel
                if hasattr(annotations, "model_dump"):
                    tool_dict["annotations"] = annotations.model_dump(exclude_none=True)
                elif isinstance(annotations, dict):
                    tool_dict["annotations"] = annotations
            out.append(tool_dict)

        self._tools_cache = out
        return out

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """呼一個 tool。回 dict(包 isError / content list)。

        錯誤交由 caller(McpToolWrapper)解讀 — 不在此層 raise。
        """
        if self._session is None:
            raise RuntimeError("McpClient not entered (use async with)")

        result = await self._session.call_tool(tool_name, arguments)

        # mcp SDK CallToolResult.content / isError → 轉 dict
        out: dict[str, Any] = {}
        is_error = getattr(result, "isError", False)
        out["isError"] = bool(is_error)

        content = getattr(result, "content", []) or []
        out_content: list[dict[str, Any]] = []
        for item in content:
            if hasattr(item, "model_dump"):
                out_content.append(item.model_dump(exclude_none=True))
            elif isinstance(item, dict):
                out_content.append(item)
        out["content"] = out_content
        return out
