"""ConfigTool — CLI-only。對應 TS ConfigTool。

讀寫 user-level settings(`~/.orion/settings.json`)。本工具讓 agent 在對話
中查 / 改 user 設定。Phase 31-I 後從 orion-sdk 搬到 CLI host:
- Cowork:用 SQLite `cowork_prefs`,不該寫 settings.json
- chat-api:多租戶,LLM 不該改 global config(安全)
- CLI:settings.json 是它的家,LLM 改 OK

SDK 內部其他模組(permissions / migrations)讀寫 settings.json 走
`orion_sdk.settings.{settings_path, load_settings, save_settings}`(SDK 自帶
helper,不再透過這個 Tool)。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Literal

from pydantic import Field

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput
from orion_sdk.settings import load_settings, save_settings


# ─── dot-path helpers ────────────────────────────────────────────────────


def _get_at(d: dict[str, Any], dotted: str) -> Any:
    cur: Any = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _set_at(d: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur = d
    for part in parts[:-1]:
        if part not in cur or not isinstance(cur[part], dict):
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value


def _del_at(d: dict[str, Any], dotted: str) -> bool:
    parts = dotted.split(".")
    cur: Any = d
    for part in parts[:-1]:
        if not isinstance(cur, dict) or part not in cur:
            return False
        cur = cur[part]
    if isinstance(cur, dict) and parts[-1] in cur:
        del cur[parts[-1]]
        return True
    return False


# ─── Tool ────────────────────────────────────────────────────────────────


class ConfigInput(ToolInput):
    action: Literal["get", "set", "delete", "list"] = Field(
        ..., description="Action to perform.",
    )
    key: str = Field(
        default="",
        description="Dot-path to the setting (e.g. 'hooks.PreToolUse'). Required for get/set/delete.",
    )
    value_json: str = Field(
        default="",
        description="JSON-encoded value (only for action='set').",
    )


class ConfigTool:
    name = "Config"
    description = (
        "Read or modify user settings stored at ~/.orion/settings.json. "
        "Supports get / set / delete / list. Use dot-paths for nested keys."
    )
    input_schema = ConfigInput

    async def call(
        self,
        input: ConfigInput,
        ctx: AgentContext,  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        settings = load_settings()

        if input.action == "list":
            keys = sorted(settings.keys())
            yield TextEvent(text=f"top-level keys: {keys}")
            return

        if not input.key:
            yield ErrorEvent(message=f"key is required for action {input.action!r}")
            return

        if input.action == "get":
            v = _get_at(settings, input.key)
            if v is None:
                yield TextEvent(text=f"{input.key}: <not set>")
            else:
                yield TextEvent(text=f"{input.key}: {json.dumps(v, indent=2)}")
            return

        if input.action == "set":
            try:
                value = json.loads(input.value_json) if input.value_json else None
            except json.JSONDecodeError as e:
                yield ErrorEvent(message=f"invalid JSON for value: {e}")
                return
            _set_at(settings, input.key, value)
            try:
                save_settings(settings)
            except OSError as e:
                yield ErrorEvent(message=f"failed to save settings: {e}")
                return
            yield TextEvent(text=f"set {input.key} = {json.dumps(value)}")
            return

        if input.action == "delete":
            removed = _del_at(settings, input.key)
            if not removed:
                yield ErrorEvent(message=f"key not found: {input.key}")
                return
            try:
                save_settings(settings)
            except OSError as e:
                yield ErrorEvent(message=f"failed to save settings: {e}")
                return
            yield TextEvent(text=f"deleted {input.key}")
            return

        yield ErrorEvent(message=f"unknown action: {input.action!r}")

    def is_concurrency_safe(self, input: ConfigInput) -> bool:  # noqa: ARG002
        return False  # 寫檔不安全並發

    def is_read_only(self, input: ConfigInput) -> bool:
        return input.action in ("get", "list")

    def max_result_size_chars(self) -> int | float:
        return 10_000
