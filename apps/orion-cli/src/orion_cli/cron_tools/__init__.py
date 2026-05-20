"""Cron tools — APScheduler-backed cron schedule。

**CLI-only**:後從 orion-sdk 搬到 CLI host,因為只 CLI 用 shell
based cron(Cowork 有自己的 LLM 對話排程走 ScheduleCreate / LoopCreate,跟
shell cron 不重疊)。SDK 不再背 apscheduler dep。
"""

from __future__ import annotations

from typing import Any

from orion_cli.cron_tools.cron_create import CronCreateInput, CronCreateTool
from orion_cli.cron_tools.cron_delete import CronDeleteInput, CronDeleteTool
from orion_cli.cron_tools.cron_list import CronListInput, CronListTool
from orion_cli.cron_tools.scheduler import (
    CronJob,
    CronScheduler,
    get_scheduler,
    reset_scheduler,
)


def build_cron_tools() -> list[Any]:
    """所有 cron tools 一次回。Caller(`__main__.py`)再給 build_default_tool_set
    的 `extra_tools=` kwarg。"""
    return [CronCreateTool(), CronListTool(), CronDeleteTool()]


def cron_tool_group() -> dict[str, Any]:
    """Cron group metadata,給 list_builtin_tool_groups(extra_groups=...) 用。"""
    return {
        "group": "Cron",
        "tools": [{"name": t.name, "description": t.description} for t in build_cron_tools()],
    }


__all__ = [
    "CronCreateInput",
    "CronCreateTool",
    "CronDeleteInput",
    "CronDeleteTool",
    "CronJob",
    "CronListInput",
    "CronListTool",
    "CronScheduler",
    "build_cron_tools",
    "cron_tool_group",
    "get_scheduler",
    "reset_scheduler",
]
