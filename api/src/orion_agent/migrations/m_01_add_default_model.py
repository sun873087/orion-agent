"""v01:加 default model 欄位(若 settings 沒有的話)。

對應 TS migrations 中 model 欄位的初始化。Phase 13。
"""

from __future__ import annotations

from typing import Any

from orion_agent.migrations.framework import Migration

_DEFAULT_MODEL = "claude-sonnet-4-6"


def up(settings: dict[str, Any]) -> dict[str, Any]:
    if "model" not in settings:
        settings["model"] = _DEFAULT_MODEL
    return settings


MIGRATION = Migration(
    version="01",
    description="Add default model field",
    up=up,
)
