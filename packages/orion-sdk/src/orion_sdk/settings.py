"""SDK 內部 `~/.orion/settings.json` 讀寫 helper。

提供 `settings_path()` / `load_settings()` / `save_settings()` 三支純函式,
給 SDK 內 `permissions/persistence.py`、`migrations/framework.py` 等模組用。

**LLM-facing 的 `Config` tool 不在這** — 那是 host 級工具(只 CLI 註冊,
Cowork 用 SQLite cowork_prefs / chat-api 多租戶不該開放給 LLM 改 global
config)。class 在 `apps/orion-cli/src/orion_cli/config_tool.py`。

寫入 atomic(寫 `.tmp` 後 rename)。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


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


__all__ = ["settings_path", "load_settings", "save_settings"]
