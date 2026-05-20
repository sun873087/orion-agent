"""MCP(Model Context Protocol)整合層。

對應 spec(`docs/phases/05-mcp-integration.md`)。

讓 agent 動態載入外部 MCP server 提供的工具(filesystem / GitHub / Slack 等),
而非寫死在程式裡。MCP 是協議,不是 agent framework — 用官方 `mcp` Python SDK
作為 thin protocol wrapper。

工具命名:`mcp__<server>__<tool_name>`,避免跟 內建工具衝突。

範圍:
- stdio + http transport(SSE / InProcess 留)
- 本機 OAuth callback(stub,實作延後)
- 動態 JSON Schema → Pydantic 建模(限扁平 object)
- mcp_instructions system prompt 動態段(接點)
- Large output 持久化(接 mcp_output stub)

故意先不做(/ 6+):
- Server-side OAuth(web chat FastAPI)
- Elicitation(-32042 反問 user)
- 圖片自動壓縮
- _meta['anthropic/alwaysLoad']
"""

from orion_sdk.mcp.config import (
    McpServerConfig,
    StdioMcpConfig,
    load_mcp_config,
)
from orion_sdk.mcp.manager import McpManager

__all__ = [
    "McpManager",
    "McpServerConfig",
    "StdioMcpConfig",
    "load_mcp_config",
]
