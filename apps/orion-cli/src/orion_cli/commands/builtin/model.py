"""/model — 切換 Conversation 用的 LLM model(同 provider)。

對應 TS commands/model/。Phase 11 範圍只支援同 provider 內換 model;換 provider
要重建 Conversation(留 Phase 11c)。

用法:
    /model                    # 顯示當前 model
    /model claude-haiku-4-5   # 切換到 haiku
    /model list               # 列已知 model
"""

from __future__ import annotations

from typing import Any

from orion_cli.commands.types import CommandResult

_KNOWN_MODELS = (
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
    "gpt-4o",
    "gpt-4o-mini",
)


class ModelCommand:
    name = "model"
    description = "Show or switch the current LLM model."

    async def execute(
        self,
        args: str,
        ctx: Any,  # noqa: ARG002
        conversation: Any,
    ) -> CommandResult:
        provider = getattr(conversation, "provider", None)
        if provider is None:
            return CommandResult(text="(no provider on conversation)")

        token = args.strip()

        if not token:
            return CommandResult(
                text=(
                    f"current model: {provider.model} "
                    f"(provider={provider.name})"
                ),
            )

        if token == "list":
            lines = ["Known models:"]
            for m in _KNOWN_MODELS:
                marker = " *" if m == provider.model else "  "
                lines.append(f"{marker} {m}")
            return CommandResult(text="\n".join(lines))

        # 切換 model — 同 provider 內換 .model 屬性即可(provider HTTP wrapper 用 model)
        old = provider.model
        try:
            provider.model = token
        except AttributeError:
            return CommandResult(
                text=f"provider {provider.name!r} does not support model switch",
            )
        return CommandResult(
            text=f"model: {old} → {token}",
            side_effect=f"switched model to {token}",
        )
