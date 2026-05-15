"""Slash commands — Phase 11。

`Command` Protocol + `CommandResult` + 全域 registry。
內建 `/help` `/model`(其餘 spec 推薦由前端 UI 取代)。

Plugin 可註冊新命令(Phase 8 plugin manifest 加 commands 欄位 — 留 Phase 11c)。
"""

from __future__ import annotations

from orion_cli.commands.registry import (
    clear_registry,
    get_command,
    list_commands,
    register_builtins,
    register_command,
)
from orion_cli.commands.types import Command, CommandResult

__all__ = [
    "Command",
    "CommandResult",
    "clear_registry",
    "get_command",
    "list_commands",
    "register_builtins",
    "register_command",
]
