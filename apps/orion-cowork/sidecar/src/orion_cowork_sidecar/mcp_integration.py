"""Cowork MCP integration(Phase 31-D 下)。

Cowork 用獨立 mcp.json — `~/.orion-cowork/mcp.json`(跟 CLI/chat-api 的
~/.orion/mcp.json 分開,因為 Cowork 是獨立桌機 app,有自己的 server pref)。

Lifecycle:
  manager.start()    啟動 McpManager + Supervisor,connect 所有 server
  manager.tools      給 Conversation inject 的 tools list
  manager.list()     UI 顯示的 server 狀態
  manager.shutdown() sidecar 退出時清理
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orion_sdk.mcp.config import HttpMcpConfig, McpServerConfig, StdioMcpConfig
from orion_sdk.mcp.manager import McpManager
from orion_sdk.mcp.supervisor import McpSupervisor

from orion_cowork_sidecar.storage import data_dir

log = logging.getLogger(__name__)


def cowork_mcp_config_path() -> Path:
    return data_dir() / "mcp.json"


def _load_cowork_configs() -> dict[str, McpServerConfig]:
    """讀 Cowork 自己的 mcp.json。失敗回空 dict(不 raise)。

    格式跟 SDK 一致:
        {
          "mcpServers": {
            "filesystem": {
              "type": "stdio",
              "command": "npx",
              "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"]
            }
          }
        }
    """
    path = cowork_mcp_config_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        return {}

    parsed: dict[str, McpServerConfig] = {}
    for name, raw in servers.items():
        if not isinstance(raw, dict):
            continue
        try:
            t = raw.get("type", "stdio")
            if t == "stdio":
                parsed[name] = StdioMcpConfig.model_validate(raw)
            elif t == "http":
                parsed[name] = HttpMcpConfig.model_validate(raw)
        except Exception:  # noqa: BLE001
            continue
    return parsed


@dataclass
class McpServerStatus:
    name: str
    status: str  # connected / failed / pending
    error: str | None
    tools: list[str]


class CoworkMcpManager:
    """Wrapper:lifecycle + status query 給 sidecar 用。

    - start() 跑一次,建 McpManager 並進 async with
    - 同時起 McpSupervisor 自動重連 failed server
    - tools_for(conv_tools) 把 SDK 內建 tools 跟 MCP wrapper 合併
    - shutdown() 退出時釋放
    """

    def __init__(self) -> None:
        self._stack: AsyncExitStack | None = None
        self._manager: McpManager | None = None
        self._supervisor: McpSupervisor | None = None
        self._supervisor_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        # 當前 active extra configs(project layer)— 用來判斷要不要 reload
        self._active_extra: dict[str, McpServerConfig] = {}

    async def start(self, extra_configs: dict[str, McpServerConfig] | None = None) -> None:
        """extra_configs 是 project-level merge — 跟 global mcp.json union,後勝同名。"""
        async with self._lock:
            if self._manager is not None:
                return
            configs = _load_cowork_configs()
            if extra_configs:
                configs = {**configs, **extra_configs}
            self._active_extra = extra_configs or {}
            self._stack = AsyncExitStack()
            mgr = McpManager(configs=configs)
            self._manager = await self._stack.enter_async_context(mgr)
            self._supervisor = McpSupervisor(self._manager)
            self._supervisor_task = asyncio.create_task(self._supervisor.run())

    async def shutdown(self) -> None:
        if self._supervisor is not None:
            self._supervisor.stop()
            if self._supervisor_task is not None:
                try:
                    await asyncio.wait_for(self._supervisor_task, timeout=2.0)
                except (asyncio.TimeoutError, Exception):
                    pass
            self._supervisor_task = None
            self._supervisor = None
        if self._stack is not None:
            try:
                await self._stack.aclose()
            except Exception:  # noqa: BLE001
                pass
            self._stack = None
        self._manager = None

    @property
    def tools(self) -> list[Any]:
        if self._manager is None:
            return []
        return list(self._manager.tools)

    def list_status(self) -> list[McpServerStatus]:
        if self._manager is None:
            return []
        connected = self._manager.connected_servers
        errors = self._manager.connection_errors
        out: list[McpServerStatus] = []

        # 從原 configs 反推全 server,標記狀態
        configs = self._manager.configs
        for name in configs:
            if name in connected:
                tool_names = [
                    t.name for t in self._manager.tools
                    if t.name.startswith(f"mcp__{name}__")
                ]
                out.append(McpServerStatus(
                    name=name,
                    status="connected",
                    error=None,
                    tools=tool_names,
                ))
            elif name in errors:
                gave_up = (
                    self._supervisor is not None
                    and self._supervisor.has_given_up(name)
                )
                out.append(McpServerStatus(
                    name=name,
                    status="gave_up" if gave_up else "failed",
                    error=errors[name],
                    tools=[],
                ))
            else:
                out.append(McpServerStatus(
                    name=name,
                    status="pending",
                    error=None,
                    tools=[],
                ))
        return out

    async def reconnect(self, name: str) -> bool:
        """手動重試。reset supervisor 的 attempt counter,再呼一次 manager。"""
        if self._manager is None:
            return False
        if self._supervisor is not None:
            self._supervisor.reset_attempts(name)
        return await self._manager.reconnect(name)

    async def reload(self, extra_configs: dict[str, McpServerConfig] | None = None) -> None:
        """完整 shutdown + restart,可附帶 project layer 的 extra configs。"""
        await self.shutdown()
        await self.start(extra_configs=extra_configs)

    @property
    def active_extra(self) -> dict[str, McpServerConfig]:
        return self._active_extra


def load_project_mcp_configs(workspace_dir: Path) -> dict[str, McpServerConfig]:
    """讀 <workspace>/.orion-cowork/mcp.json,parse 成 McpServerConfig dict。"""
    path = workspace_dir / ".orion-cowork" / "mcp.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        return {}
    parsed: dict[str, McpServerConfig] = {}
    for name, raw in servers.items():
        if not isinstance(raw, dict):
            continue
        try:
            t = raw.get("type", "stdio")
            if t == "stdio":
                parsed[name] = StdioMcpConfig.model_validate(raw)
            elif t == "http":
                parsed[name] = HttpMcpConfig.model_validate(raw)
        except Exception:  # noqa: BLE001
            continue
    return parsed


def read_mcp_config_raw() -> dict[str, dict[str, Any]]:
    """直接讀 mcp.json 內的 mcpServers dict,給 UI 顯示用(含未驗 config)。"""
    path = cowork_mcp_config_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for name, raw in servers.items():
        if isinstance(raw, dict):
            out[name] = raw
    return out


def write_mcp_config_raw(servers: dict[str, dict[str, Any]]) -> None:
    """atomic write — tmp file + rename。"""
    path = cowork_mcp_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"mcpServers": servers}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
