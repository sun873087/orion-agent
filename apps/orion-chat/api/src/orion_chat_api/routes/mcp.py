"""/mcp/servers — per-user MCP server 設定 CRUD。

存 `~/.orion/users/<uid>/mcp.json`(per-user,非全域)。multi-tenant 下只允許
**remote transport(sse / http / ws)**:stdio 會在 server 主機 spawn 子行程,
跨租戶高風險,一律拒。

連線:ws 連上時由 mcp_loader.load_user_http_mcp_configs 載入、McpManager 連線,
工具併進該對話的 tool set(見 chat.py)。目前 SDK transport 只實作 streamable-http,
所以實際接得上的是 transport=http;sse / ws 等 SDK 補對應 transport 再生效。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from orion_chat_api.deps import current_user
from orion_sdk.memory.paths import user_memory_paths

router = APIRouter()

_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


def _mcp_path(user_id: str) -> Path:
    return user_memory_paths(user_id).root / "mcp.json"


def _load(user_id: str) -> dict[str, dict]:
    path = _mcp_path(user_id)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    servers = data.get("servers")
    return servers if isinstance(servers, dict) else {}


def _save(user_id: str, servers: dict[str, dict]) -> None:
    path = _mcp_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"servers": servers}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


class McpServer(BaseModel):
    name: str
    transport: str
    url: str


class McpServerBody(BaseModel):
    transport: Literal["sse", "http", "ws"]  # stdio 不允許(multi-tenant)
    url: str


@router.get("/mcp/servers", response_model=list[McpServer])
async def list_mcp_servers(
    user_id: Annotated[str, Depends(current_user)],
) -> list[McpServer]:
    servers = _load(user_id)
    return [
        McpServer(
            name=name,
            transport=str(cfg.get("transport", "")),
            url=str(cfg.get("url", "")),
        )
        for name, cfg in sorted(servers.items())
    ]


@router.put("/mcp/servers/{name}", response_model=McpServer)
async def put_mcp_server(
    name: str,
    body: McpServerBody,
    user_id: Annotated[str, Depends(current_user)],
) -> McpServer:
    if name in (".", "..") or not _NAME_PATTERN.match(name):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"invalid server name {name!r}",
        )
    servers = _load(user_id)
    servers[name] = {"transport": body.transport, "url": body.url}
    _save(user_id, servers)
    return McpServer(name=name, transport=body.transport, url=body.url)


@router.delete("/mcp/servers/{name}")
async def delete_mcp_server(
    name: str,
    user_id: Annotated[str, Depends(current_user)],
) -> dict[str, bool]:
    servers = _load(user_id)
    existed = servers.pop(name, None) is not None
    if existed:
        _save(user_id, servers)
    return {"deleted": existed}
