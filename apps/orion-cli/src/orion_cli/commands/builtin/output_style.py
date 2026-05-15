"""/output-style — 切換 Conversation 的 output style。Phase 13。

對應 TS Claude Code `src/commands/outputStyle/`。

用法:
    /output-style                 # 顯示當前 style 與可用清單
    /output-style <name>          # 切換成 <name>(寫進 conversation.output_style)
    /output-style none            # 清除選用 style
    /output-style list            # 同無參數,只列可用清單
"""

from __future__ import annotations

from typing import Any

from orion_cli.commands.types import CommandResult
from orion_sdk.output_styles import (
    find_output_style,
    list_output_style_names,
    load_all_output_styles,
)


class OutputStyleCommand:
    name = "output-style"
    description = "Show or switch the current output style."

    async def execute(
        self,
        args: str,
        ctx: Any,  # noqa: ARG002
        conversation: Any,
    ) -> CommandResult:
        token = args.strip()

        if not token or token == "list":
            current = getattr(conversation, "output_style", None) or "(none)"
            styles = load_all_output_styles()
            if not styles:
                return CommandResult(
                    text=(
                        f"current style: {current}\n\n"
                        "No output styles found. "
                        "Add `*.md` files under "
                        "`$ORION_HOME/output-styles/` or "
                        "`<cwd>/.orion/output-styles/`."
                    ),
                )
            lines = [f"current style: {current}", "", "Available styles:"]
            for s in sorted(styles, key=lambda x: x.name):
                desc = f" — {s.description}" if s.description else ""
                marker = "*" if s.name == current else " "
                lines.append(f" {marker} {s.name}{desc}")
            return CommandResult(text="\n".join(lines))

        if token in ("none", "clear", "off"):
            old = getattr(conversation, "output_style", None) or "(none)"
            try:
                conversation.output_style = None
            except AttributeError:
                return CommandResult(
                    text="conversation does not support output_style",
                )
            return CommandResult(
                text=f"output style: {old} → (none)",
                side_effect="cleared output style",
            )

        if token not in list_output_style_names():
            return CommandResult(
                text=(
                    f"output style {token!r} not found. "
                    f"Use `/output-style list` to see available styles."
                ),
            )

        # sanity:確認真的能 load(防 race / fs 中途消失)
        if find_output_style(token) is None:
            return CommandResult(
                text=f"output style {token!r} could not be loaded.",
            )

        old = getattr(conversation, "output_style", None) or "(none)"
        try:
            conversation.output_style = token
        except AttributeError:
            return CommandResult(
                text="conversation does not support output_style",
            )
        return CommandResult(
            text=f"output style: {old} → {token}",
            side_effect=f"switched output style to {token}",
        )
