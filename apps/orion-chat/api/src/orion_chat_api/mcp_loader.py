"""讀 per-user mcp.json → remote MCP config(接進對話的 tool set)。

multi-tenant 安全界線:**只允 remote transport,禁 stdio** —— stdio 會在 server 主機
spawn 子行程,等於讓租戶執行任意命令。寫入端(routes/mcp.py)的 McpServerBody 已只收
sse/http/ws;這裡再過濾一次當第二道防線。

格式對齊 routes/mcp.py 的 `_save`:`{"servers": {name: {"transport", "url"}}}`。
目前 SDK transport 只實作了 streamable-http(見 mcp/transports.py),所以只有
transport == "http" 會真的接上;sse / ws 留待 SDK 補對應 transport。
"""

from __future__ import annotations

import json

from orion_sdk.mcp.config import HttpMcpConfig
from orion_sdk.memory.paths import user_memory_paths


def _mcp_path(user_id: str):  # type: ignore[no-untyped-def]
    return user_memory_paths(user_id).root / "mcp.json"


def load_user_http_mcp_configs(user_id: str) -> dict[str, HttpMcpConfig]:
    """回 {name: HttpMcpConfig}(只含 transport=http)。檔不存在 / 壞掉回空 dict。"""
    path = _mcp_path(user_id)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    servers = data.get("servers") if isinstance(data, dict) else None
    out: dict[str, HttpMcpConfig] = {}
    if not isinstance(servers, dict):
        return out
    for name, cfg in servers.items():
        if not isinstance(cfg, dict):
            continue
        url = cfg.get("url")
        if cfg.get("transport") == "http" and isinstance(url, str) and url:
            out[name] = HttpMcpConfig(url=url)
    return out
