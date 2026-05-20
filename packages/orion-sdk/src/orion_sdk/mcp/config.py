"""MCP server 設定載入。

對應 spec § 5 config.py。

支援兩種 transport(範圍):
- **stdio**:本機 subprocess,主流;`{type: "stdio", command: "...", args: [...]}`
- **http**:遠端 HTTP server;`{type: "http", url: "..."}`(透過 mcp SDK 直接,
  不額外手刻;config 結構備好)

讀取優先順序(後者覆蓋前者同 server name):
1. `~/.orion/mcp.json`(global)
2. `<cwd>/.orion/mcp.json`(per-project)
3. CLI 顯式指定路徑(最高)

JSON 格式:
```json
{
  "mcpServers": {
    "fs": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
      "env": {"DEBUG": "1"}
    },
    "remote": {
      "type": "http",
      "url": "https://example.com/mcp"
    }
  }
}
```
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class StdioMcpConfig(BaseModel):
    """本機 subprocess 啟動的 MCP server。"""

    type: Literal["stdio"] = "stdio"
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] | None = None


class HttpMcpConfig(BaseModel):
    """遠端 HTTP MCP server。"""

    type: Literal["http"] = "http"
    url: str
    headers: dict[str, str] | None = None


McpServerConfig = Annotated[
    StdioMcpConfig | HttpMcpConfig,
    Field(discriminator="type"),
]


_CONFIG_FILE = "mcp.json"


def _candidate_config_paths(
    cwd: Path | None = None,
    extra: Path | None = None,
) -> list[Path]:
    """回所有可能的 config 路徑(順序由低到高優先)。"""
    cwd = cwd or Path.cwd()
    paths = [
        Path.home() / ".orion" / _CONFIG_FILE,
        cwd / ".orion" / _CONFIG_FILE,
    ]
    if extra is not None:
        paths.append(extra)
    return paths


def _load_one(path: Path) -> dict[str, dict[str, object]]:
    """讀單一 mcp.json 回 mcpServers dict。失敗回空 dict。"""
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        return {}
    # 過濾非 dict 的 entry
    return {k: v for k, v in servers.items() if isinstance(v, dict)}


def load_mcp_config(
    cwd: Path | None = None,
    extra_path: Path | None = None,
) -> dict[str, McpServerConfig]:
    """讀全部 config 並合併。後者(高優先)覆蓋同 name 的前者。

    Returns:
        dict: server_name → McpServerConfig
    """
    raw_merged: dict[str, dict[str, object]] = {}
    for p in _candidate_config_paths(cwd, extra_path):
        raw_merged.update(_load_one(p))

    parsed: dict[str, McpServerConfig] = {}
    for name, raw in raw_merged.items():
        try:
            t = raw.get("type", "stdio")
            if t == "stdio":
                parsed[name] = StdioMcpConfig.model_validate(raw)
            elif t == "http":
                parsed[name] = HttpMcpConfig.model_validate(raw)
            # 其他 type 忽略(範圍外)
        except Exception: # noqa: BLE001 — 個別 server 設定壞不該炸全部
            continue

    return parsed


# Helper: import os 留著供 future 用(讀環境變數覆蓋等)
_ = os
