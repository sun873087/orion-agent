"""Plugins package。

Plugin 一鍵安裝多種延伸:skill + hook + MCP server。`plugin.json` 描述 manifest。

Public API:
- `PluginManifest` — 載入後的 dataclass
- `discover_plugins(roots)` 掃多個目錄找 `*/plugin.json`
- `load_all_plugins(settings, *, hook_registry, ...)` enable 的 plugin 一次接好
- `enable_plugin(...)` / `disable_plugin(...)` — 寫 settings.json
"""

from __future__ import annotations

from orion_sdk.plugins.loader import (
    discover_plugins,
    enable_plugin,
    get_enabled_plugins,
    load_all_plugins,
)
from orion_sdk.plugins.types import PluginManifest

__all__ = [
    "PluginManifest",
    "discover_plugins",
    "enable_plugin",
    "get_enabled_plugins",
    "load_all_plugins",
]
