"""Special tools — Phase 10。

- ToolSearchTool:deferred tool 動態載入
- SyntheticOutputTool:強制 JSON Schema 結構化輸出
- SleepTool:autonomous agent 用,延遲下一輪
"""

from __future__ import annotations

from orion_agent.tools.special.sleep import SleepInput, SleepTool
from orion_agent.tools.special.synthetic_output import (
    SyntheticOutputInput,
    SyntheticOutputTool,
)
from orion_agent.tools.special.tool_search import ToolSearchInput, ToolSearchTool

__all__ = [
    "SleepInput",
    "SleepTool",
    "SyntheticOutputInput",
    "SyntheticOutputTool",
    "ToolSearchInput",
    "ToolSearchTool",
]
