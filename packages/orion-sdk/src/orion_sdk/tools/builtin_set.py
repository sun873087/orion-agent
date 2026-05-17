"""共用內建工具集 — 給 CLI(`main.py`)和 web chat route(`api/routes/sessions.py`)用。

`AskUserQuestionTool` 永遠註冊。CLI 在這裡傳 stdin asker;web chat 在 ws 連上時
透過 `chat.py` 把 ws asker 設到 tool.asker 上(per-connection late-bind)。
asker 是 None 時呼叫 tool 會回 ErrorEvent(模型可看到 schema、知道工具存在)。

Host-specific tools(Browser / Cron 等)不在這 — 由 host 透過 `extra_tools`
注入,SDK 不背 playwright / apscheduler 這類 dep。
"""

from __future__ import annotations

from typing import Any

from orion_sdk.core.tool import Tool
from orion_sdk.tools.agent.skill_tool import SkillTool
from orion_sdk.tools.config.config_tool import ConfigTool
from orion_sdk.tools.file.edit import FileEditTool
from orion_sdk.tools.file.notebook_edit import NotebookEditTool
from orion_sdk.tools.file.read import FileReadTool
from orion_sdk.tools.file.write import FileWriteTool
from orion_sdk.tools.interactive.ask_user import (
    AskUserCallback,
    AskUserQuestionTool,
)
from orion_sdk.tools.schedule import (
    LoopCreateTool,
    ScheduleCreateTool,
    ScheduleDeleteTool,
    ScheduleListTool,
)
from orion_sdk.tools.search.glob import GlobTool
from orion_sdk.tools.search.grep import GrepTool
from orion_sdk.tools.shell.bash import BashTool
from orion_sdk.tools.special.sleep import SleepTool
from orion_sdk.tools.special.synthetic_output import SyntheticOutputTool
from orion_sdk.tools.special.tool_search import ToolSearchTool
from orion_sdk.tools.task.task_create import TaskCreateTool
from orion_sdk.tools.task.task_get import TaskGetTool
from orion_sdk.tools.task.task_list import TaskListTool
from orion_sdk.tools.task.task_output import TaskOutputTool
from orion_sdk.tools.task.task_stop import TaskStopTool
from orion_sdk.tools.task.task_update import TaskUpdateTool
from orion_sdk.tools.todo.todo_write import TodoWriteTool
from orion_sdk.tools.web.fetch import WebFetchTool
from orion_sdk.tools.web.search import WebSearchTool
from orion_sdk.tools.workdir.enter import EnterWorkdirTool
from orion_sdk.tools.workdir.exit import ExitWorkdirTool


def build_default_tool_set(
    asker: AskUserCallback | None = None,
    *,
    disabled_tools: set[str] | None = None,
    schedule_callbacks: dict[str, Any] | None = None,
    extra_tools: list[Tool[Any]] | None = None,
) -> list[Tool[Any]]:
    """組所有內建工具。

    Args:
        asker: 給 AskUserQuestionTool 用的 callback。None 也會註冊 tool
            (asker 之後可由 caller 設到 tool.asker — 例如 chat.py 的 ws 連線
            掛上 ws asker)。模型若在 asker=None 時呼叫 tool 會收到 ErrorEvent。
        disabled_tools: 名字在這 set 內的 tool 不會被註冊。
            Cowork 從 user prefs 讀進來,讓使用者按組 / 個別關。
        schedule_callbacks: 給 Schedule* tools 用的 sidecar callback dict。
            預期 keys: 'create' / 'list' / 'delete' / 'loop_create'。
            None 時 Schedule tools 不註冊(只有 Cowork 啟用)。
        extra_tools: host 注入的工具 — 譬如 Cowork 的 Browser*、CLI 的 Cron*、
            Cowork 的 OpenUrl/OpenPath 等。SDK 本身不註冊 playwright / apscheduler
            這類綁特定 runtime 的工具。

    Returns:
        Tool list,結尾自動加 ToolSearchTool(self-aware)。
    """
    disabled = disabled_tools or set()
    all_candidates: list[Tool[Any]] = [
        # Phase 1 — 基礎
        FileReadTool(),
        FileWriteTool(),
        FileEditTool(),
        BashTool(),
        GlobTool(),
        GrepTool(),
        WebFetchTool(),
        WebSearchTool(),
        SkillTool(),
        TodoWriteTool(),
        # Phase 9 — workdir
        EnterWorkdirTool(),
        ExitWorkdirTool(),
        # Phase 10 — special
        SleepTool(),
        SyntheticOutputTool(),
        # Phase 10 — config
        ConfigTool(),
        # Phase 10 — notebook
        NotebookEditTool(),
        # Phase 10 — task
        TaskCreateTool(),
        TaskGetTool(),
        TaskListTool(),
        TaskUpdateTool(),
        TaskStopTool(),
        TaskOutputTool(),
    ]
    # Schedule tools(對話排程) — 需要 host 提供 callbacks 才註冊
    if schedule_callbacks:
        if "create" in schedule_callbacks:
            all_candidates.append(ScheduleCreateTool(callback=schedule_callbacks["create"]))
        if "list" in schedule_callbacks:
            all_candidates.append(ScheduleListTool(callback=schedule_callbacks["list"]))
        if "delete" in schedule_callbacks:
            all_candidates.append(ScheduleDeleteTool(callback=schedule_callbacks["delete"]))
        if "loop_create" in schedule_callbacks:
            all_candidates.append(LoopCreateTool(callback=schedule_callbacks["loop_create"]))
    # Host-specific tools(Browser / Cron / OpenUrl / OpenPath / ...)
    if extra_tools:
        all_candidates.extend(extra_tools)
    base: list[Tool[Any]] = [t for t in all_candidates if t.name not in disabled]

    # AskUserQuestion / ToolSearch 視為「核心 infra」— 也可被 disable,但通常不會
    ask_tool = AskUserQuestionTool(asker=asker)
    if ask_tool.name not in disabled:
        base.append(ask_tool)
    search_tool = ToolSearchTool(all_tools=base)
    if search_tool.name not in disabled:
        base.append(search_tool)
    return base


def list_builtin_tool_groups(
    *,
    extra_groups: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """回 builtin tools 的分組 metadata,給 settings UI 顯示「組別 + 展開個別」用。

    結構:[{ group: str, tools: [{name, description}] }]。MCP tools 不在這 — 它們
    是動態 plug-in,UI 走另一個來源(mcp.list)。Host-specific group(Cowork Browser /
    CLI Cron)由各 host 透過 `extra_groups` 注入。
    """
    from orion_sdk.tools.interactive.ask_user import AskUserQuestionTool

    def to_dict(t: Any) -> dict[str, str]:
        return {"name": t.name, "description": t.description}

    groups: list[dict[str, Any]] = [
        {
            "group": "File",
            "tools": [to_dict(t) for t in (FileReadTool(), FileWriteTool(), FileEditTool(), NotebookEditTool())],
        },
        {"group": "Shell", "tools": [to_dict(BashTool())]},
        {"group": "Search", "tools": [to_dict(GlobTool()), to_dict(GrepTool())]},
        {"group": "Web", "tools": [to_dict(WebFetchTool()), to_dict(WebSearchTool())]},
        {"group": "Skill", "tools": [to_dict(SkillTool())]},
        {
            "group": "Schedule",
            "tools": [
                to_dict(ScheduleCreateTool()),
                to_dict(ScheduleListTool()),
                to_dict(ScheduleDeleteTool()),
                to_dict(LoopCreateTool()),
            ],
        },
        {"group": "Todo", "tools": [to_dict(TodoWriteTool())]},
        {"group": "Workdir", "tools": [to_dict(EnterWorkdirTool()), to_dict(ExitWorkdirTool())]},
        {
            "group": "System",
            "tools": [to_dict(SleepTool()), to_dict(SyntheticOutputTool()), to_dict(ConfigTool())],
        },
        {
            "group": "Task",
            "tools": [
                to_dict(TaskCreateTool()), to_dict(TaskGetTool()), to_dict(TaskListTool()),
                to_dict(TaskUpdateTool()), to_dict(TaskStopTool()), to_dict(TaskOutputTool()),
            ],
        },
        {
            "group": "Interactive",
            "tools": [to_dict(AskUserQuestionTool(asker=None))],
        },
    ]
    if extra_groups:
        groups.extend(extra_groups)
    return groups


__all__ = ["build_default_tool_set", "list_builtin_tool_groups"]
