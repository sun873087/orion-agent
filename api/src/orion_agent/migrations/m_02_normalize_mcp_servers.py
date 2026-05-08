"""v02:mcpServers 結構標準化。Phase 13。

舊格式可能是字串 → 包成 `{"command": <str>, "type": "stdio"}` dict。
對應 TS migrate*.ts 的 mcp shape 標準化。
"""

from __future__ import annotations

from typing import Any

from orion_agent.migrations.framework import Migration


def up(settings: dict[str, Any]) -> dict[str, Any]:
    servers = settings.get("mcpServers")
    if not isinstance(servers, dict):
        return settings
    for name, conf in list(servers.items()):
        if isinstance(conf, str):
            servers[name] = {"command": conf, "type": "stdio"}
    return settings


MIGRATION = Migration(
    version="02",
    description="Normalize mcpServers entries to dict shape",
    up=up,
)
