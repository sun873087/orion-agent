"""Slash command 全域 registry — Phase 11。

Phase 11 範圍:單 process 全域 registry。Phase 11c 加 per-conversation override
(plugin 可註冊只限該 session 用的命令)。
"""

from __future__ import annotations

from orion_agent.commands.types import Command

_registry: dict[str, Command] = {}


def register_command(cmd: Command) -> None:
    """註冊一個命令。已存在 → ValueError(避免 typo 蓋掉內建)。"""
    if not cmd.name:
        raise ValueError("command name must be non-empty")
    if cmd.name in _registry:
        raise ValueError(f"command {cmd.name!r} already registered")
    _registry[cmd.name] = cmd


def get_command(name: str) -> Command | None:
    return _registry.get(name)


def list_commands() -> list[Command]:
    """按名稱 sort 過。"""
    return [v for _, v in sorted(_registry.items())]


def clear_registry() -> None:
    """測試用 — 清空。"""
    _registry.clear()


def register_builtins() -> None:
    """啟動時呼一次 — 註冊內建命令。

    Phase 11 範圍 2 個:/help / /model。其餘 6 個(/clear / /compact / /init /
    /memory / /cost / /history)由前端 UI 取代(Phase 11c 補回)。
    """
    from orion_agent.commands.builtin.help import HelpCommand
    from orion_agent.commands.builtin.model import ModelCommand
    from orion_agent.commands.builtin.output_style import OutputStyleCommand

    if "help" not in _registry:
        register_command(HelpCommand())
    if "model" not in _registry:
        register_command(ModelCommand())
    if "output-style" not in _registry:
        register_command(OutputStyleCommand())
