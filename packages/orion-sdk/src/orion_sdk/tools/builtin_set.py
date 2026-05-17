"""共用內建工具集 — 給 CLI(`main.py`)和 web chat route(`api/routes/sessions.py`)用。

`AskUserQuestionTool` 永遠註冊。CLI 在這裡傳 stdin asker;web chat 在 ws 連上時
透過 `chat.py` 把 ws asker 設到 tool.asker 上(per-connection late-bind)。
asker 是 None 時呼叫 tool 會回 ErrorEvent(模型可看到 schema、知道工具存在)。
"""

from __future__ import annotations

from typing import Any

from orion_sdk.core.tool import Tool
from orion_sdk.tools.agent.skill_tool import SkillTool
from orion_sdk.tools.config.config_tool import ConfigTool
from orion_sdk.tools.cron.cron_create import CronCreateTool
from orion_sdk.tools.cron.cron_delete import CronDeleteTool
from orion_sdk.tools.cron.cron_list import CronListTool
from orion_sdk.tools.file.edit import FileEditTool
from orion_sdk.tools.file.notebook_edit import NotebookEditTool
from orion_sdk.tools.file.read import FileReadTool
from orion_sdk.tools.file.write import FileWriteTool
from orion_sdk.tools.interactive.ask_user import (
    AskUserCallback,
    AskUserQuestionTool,
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
    browser_enabled: bool = True,
) -> list[Tool[Any]]:
    """組所有內建工具。

    Args:
        asker: 給 AskUserQuestionTool 用的 callback。None 也會註冊 tool
            (asker 之後可由 caller 設到 tool.asker — 例如 chat.py 的 ws 連線
            掛上 ws asker)。模型若在 asker=None 時呼叫 tool 會收到 ErrorEvent。
        browser_enabled: 自動偵測 playwright + system Chrome 是否可用,可用就
            註冊 Browser* tools(Navigate / Click / Type / Screenshot 等)。
            False 強制不註冊,即使環境支援也不放。

    Returns:
        Tool list,結尾自動加 ToolSearchTool(self-aware)。
    """
    base: list[Tool[Any]] = [
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
        # Phase 10 — cron
        CronCreateTool(),
        CronListTool(),
        CronDeleteTool(),
    ]
    # Browser use — 偵測 playwright + system Chrome 可用才註冊
    if browser_enabled:
        try:
            from orion_sdk.tools.browser import build_browser_tools, is_browser_available
            if is_browser_available():
                base.extend(build_browser_tools())  # type: ignore[arg-type]
        except ImportError:
            pass

    base.append(AskUserQuestionTool(asker=asker))
    base.append(ToolSearchTool(all_tools=base))
    return base


__all__ = ["build_default_tool_set"]
