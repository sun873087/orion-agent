"""v03:確保 settings 有 `permissions.rules` 容器。

的 permissions/persistence.py 會把「Always Allow / Always Deny」寫到
`settings.permissions.rules`。這個 migration 預先建空 list,免得後續 code
還要每次檢查 None。
"""

from __future__ import annotations

from typing import Any

from orion_sdk.migrations.framework import Migration


def up(settings: dict[str, Any]) -> dict[str, Any]:
    perms = settings.get("permissions")
    if not isinstance(perms, dict):
        perms = {}
        settings["permissions"] = perms
    rules = perms.get("rules")
    if not isinstance(rules, list):
        perms["rules"] = []
    return settings


MIGRATION = Migration(
    version="03",
    description="Initialize permissions.rules container for Always Allow/Deny",
    up=up,
)
