"""/help — 列已註冊命令清單。"""

from __future__ import annotations

from typing import Any

from orion_cli.commands.types import CommandResult


class HelpCommand:
    name = "help"
    description = "List available slash commands."

    async def execute(
        self,
        args: str,  # noqa: ARG002
        ctx: Any,  # noqa: ARG002
        conversation: Any,  # noqa: ARG002
    ) -> CommandResult:
        # 延遲 import 避免循環(registry 的 register_builtins 會 import 本檔)
        from orion_cli.commands.registry import list_commands

        cmds = list_commands()
        if not cmds:
            return CommandResult(text="(no commands registered)")

        lines = ["Available slash commands:"]
        for c in cmds:
            lines.append(f"  /{c.name:<12} {c.description}")
        return CommandResult(text="\n".join(lines))
