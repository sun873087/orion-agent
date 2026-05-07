"""ConfigTool — Phase 10。對應 TS ConfigTool。

讀寫 user-level settings(`~/.orion/settings.json`)。Phase 8 plugins / Phase 7 hooks
都從這個檔案讀。本工具讓 agent 可在對話中查 / 改 user 設定。

支援動作:
- get(key): 取單一 key(支援 dot-path 例:"hooks.PreToolUse")
- set(key, value_json): 設,value 是 JSON 字串
- delete(key): 刪 key(dot-path)
- list: 列出 top-level keys

寫入時 atomic(寫 .tmp 後 rename)。
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput


def settings_path() -> Path:
    base = os.environ.get("ORION_HOME") or str(Path.home() / ".orion")
    return Path(base) / "settings.json"


def load_settings(path: Path | None = None) -> dict[str, Any]:
    p = path or settings_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(settings: dict[str, Any], path: Path | None = None) -> None:
    p = path or settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


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
