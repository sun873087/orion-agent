"""McpManager — 集中管多個 MCP server。

對應 spec § 5 (整合層 + manager)。

一個 conversation 一個 McpManager;async context manager 管 lifecycle:
- __aenter__:讀 config → 連所有 servers → 列舉 tools → 包成 McpToolWrapper
- __aexit__:關所有 sessions

個別 server 失敗 → log 警告 + skip,不影響其他。
"""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from pathlib import Path
from types import TracebackType
from typing import Any

from orion_agent.core.tool import Tool
from orion_agent.mcp.client import McpClient
from orion_agent.mcp.config import McpServerConfig, load_mcp_config
from orion_agent.mcp.tool_wrapper import wrap_mcp_tool

logger = logging.getLogger(__name__)


class McpManager:
    """跨多個 MCP server 的集中管理。"""

    def __init__(
        self,
        configs: dict[str, McpServerConfig] | None = None,
        *,
        cwd: Path | None = None,
        extra_config_path: Path | None = None,
    ) -> None:
        """
        Args:
            configs: 直接傳入(測試用);若 None 自動 load_mcp_config
            cwd: 用以找 <cwd>/.orion/mcp.json
            extra_config_path: CLI --mcp-config 額外路徑(優先於 cwd)
        """
        if configs is None:
            self.configs = load_mcp_config(cwd=cwd, extra_path=extra_config_path)
        else:
            self.configs = configs

        self._clients: dict[str, McpClient] = {}
        self._tools: list[Tool[Any]] = []
        self._exit_stack: AsyncExitStack | None = None
        self._connection_errors: dict[str, str] = {}
        """server_name → error message(若該 server 連失敗)。"""

    async def __aenter__(self) -> McpManager:
        self._exit_stack = AsyncExitStack()
        for name, config in self.configs.items():
            try:
                client = await self._exit_stack.enter_async_context(
                    McpClient(name, config),
                )
                self._clients[name] = client

                tool_defs = await client.list_tools()
                for tool_def in tool_defs:
                    try:
                        wrapper = wrap_mcp_tool(
                            server_name=name,
                            tool_def=tool_def,
                            client=client,
                        )
                        self._tools.append(wrapper)
                    except Exception as e:  # noqa: BLE001
                        logger.warning(
                            "Failed to wrap tool %r from server %r: %s",
                            tool_def.get("name"), name, e,
                        )
            except Exception as e:  # noqa: BLE001
                self._connection_errors[name] = f"{type(e).__name__}: {e}"
                logger.warning(
                    "MCP server %r connection failed: %s — skipping", name, e,
                )
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
                logger.warning("McpManager cleanup raised: %s", e)
        self._exit_stack = None
        self._clients.clear()

    @property
    def tools(self) -> list[Tool[Any]]:
        """所有 server 的 tools 集合(McpToolWrapper)。"""
        return list(self._tools)

    @property
    def connected_servers(self) -> list[str]:
        return list(self._clients.keys())

    @property
    def connection_errors(self) -> dict[str, str]:
        return dict(self._connection_errors)

    def server_summary(self) -> str:
        """給 mcp_instructions section 用 — 每 server 一行 + 工具數。"""
        if not self._clients and not self._connection_errors:
            return ""

        lines: list[str] = []
        for name in self._clients:
            tools_for_server = [
                t for t in self._tools if t.name.startswith(f"mcp__{name}__")
            ]
            lines.append(f"- **{name}** ({len(tools_for_server)} tools)")

        for name, err in self._connection_errors.items():
            lines.append(f"- **{name}** ⚠️ failed: {err}")

        return "\n".join(lines)
