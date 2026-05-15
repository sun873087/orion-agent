"""內建 plugin — Phase 8。

對應 TS plugins/builtinPlugins.ts。內建 plugin 跟 user 自寫 plugin 一樣處理,
但寫死在程式碼。Phase 8 範圍先不放正式內建 plugin(等實際 use case)。
"""

from __future__ import annotations

from orion_sdk.plugins.types import PluginManifest


def builtin_plugins() -> list[PluginManifest]:
    """目前空清單;後續 phase 加實質內建 plugin。"""
    return []
