"""AppState — Conversation 的 UI / runtime 狀態。

對應 TS `src/state/AppState.tsx` + `AppStateStore.ts`。簡化版:
- 不做 Redux(action / reducer / middleware),Python backend 用不上
- 純 dataclass + immutable update(`dataclasses.replace`)
- caller 自己決定何時把新 state 塞回 ctx / Conversation

主要欄位:
- `tool_permission_context`:已決策過的權限歷史(allow / deny / 額外 cwd)
- `ide_context`:IDE 連線狀態(VS Code 等)
- `mcp_server_statuses`:每個 MCP server 的連線狀態
- `pending_attachments`:從 input pipeline 累積的 attachments
- `plan_mode_state` 不放這 — 那個 mutate 頻率高,放 ctx 直存比較順手
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4


@dataclass(frozen=True)
class ToolPermissionContext:
    """已決策過的工具權限歷史。

    `granted` / `denied` 用 dict-of-lists:tool_name → list 已決策的 input pattern。
    範圍只是容器,policy 細節留給 caller 解讀(白名單 / glob / pattern 等)。
    """

    granted: dict[str, tuple[str, ...]] = field(default_factory=dict)
    denied: dict[str, tuple[str, ...]] = field(default_factory=dict)
    additional_working_directories: tuple[Path, ...] = field(default_factory=tuple)
    """允許工具操作的額外 cwd(超出 ctx.cwd 的目錄)。"""

    bypass_permissions: bool = False
    """全部繞過 policy(危險,僅 dev)。"""

    def with_grant(self, tool_name: str, pattern: str) -> ToolPermissionContext:
        """加一筆 grant,回新 context(不可變)。"""
        existing = self.granted.get(tool_name, ())
        if pattern in existing:
            return self
        new_granted = {**self.granted, tool_name: (*existing, pattern)}
        return replace(self, granted=new_granted)

    def with_deny(self, tool_name: str, pattern: str) -> ToolPermissionContext:
        existing = self.denied.get(tool_name, ())
        if pattern in existing:
            return self
        new_denied = {**self.denied, tool_name: (*existing, pattern)}
        return replace(self, denied=new_denied)

    def with_additional_cwd(self, cwd: Path) -> ToolPermissionContext:
        if cwd in self.additional_working_directories:
            return self
        return replace(
            self,
            additional_working_directories=(*self.additional_working_directories, cwd),
        )


@dataclass(frozen=True)
class IDEContext:
    """IDE 連線狀態。Web app 場景下通常維持 connected=False。"""

    connected: bool = False
    selection: str | None = None
    """IDE 當前選取的文字內容(若有)。"""
    cursor_file: Path | None = None
    """IDE 當前游標所在檔案。"""


@dataclass
class AppState:
    """Conversation 級別的應用狀態(可變容器)。

    跟 `AgentContext` 不同:AgentContext 是 per-send 的執行 context(短命),
    AppState 是 Conversation 整個生命週期共用的 UI / runtime 狀態。

    immutable 子欄位(`ToolPermissionContext`、`IDEContext`)用 `dataclasses.replace`
    更新;outer AppState 本身可變,直接 mutate 子欄位 ref 即可。
    """

    session_id: UUID = field(default_factory=uuid4)
    tool_permission_context: ToolPermissionContext = field(
        default_factory=ToolPermissionContext
    )
    ide_context: IDEContext = field(default_factory=IDEContext)
    mcp_server_statuses: dict[str, str] = field(default_factory=dict)
    """server_name → "connected" / "failed" / "pending" / "disconnected"。"""

    pending_attachments: list[dict[str, Any]] = field(default_factory=list)
    """從 input pipeline 累積的 attachments(@file 內容 / 圖片 ref 等)。"""

    def grant_tool(self, tool_name: str, pattern: str) -> None:
        """便利方法:把一筆 grant 加進 tool_permission_context。"""
        self.tool_permission_context = self.tool_permission_context.with_grant(
            tool_name, pattern
        )

    def deny_tool(self, tool_name: str, pattern: str) -> None:
        self.tool_permission_context = self.tool_permission_context.with_deny(
            tool_name, pattern
        )

    def add_working_directory(self, cwd: Path) -> None:
        self.tool_permission_context = (
            self.tool_permission_context.with_additional_cwd(cwd)
        )

    def set_mcp_status(self, server_name: str, status: str) -> None:
        self.mcp_server_statuses[server_name] = status

    def is_tool_granted(self, tool_name: str, pattern: str) -> bool:
        if self.tool_permission_context.bypass_permissions:
            return True
        return pattern in self.tool_permission_context.granted.get(tool_name, ())

    def is_tool_denied(self, tool_name: str, pattern: str) -> bool:
        return pattern in self.tool_permission_context.denied.get(tool_name, ())


__all__ = [
    "AppState",
    "IDEContext",
    "ToolPermissionContext",
]
