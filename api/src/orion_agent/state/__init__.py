"""Application-level state container — Phase 12。

對應 TS Claude Code `src/state/AppState.tsx` + `AppStateStore.ts`(簡化版)。

跟 `core/state.py:AgentContext` 區別:
- AgentContext = 一次 query_loop 的執行 context(短命,跟著 conversation send 流動)
- AppState    = Conversation 級別的 UI / runtime 狀態(權限歷史、IDE、MCP 健康等)

Python backend 不需要 Redux 全套 — 用 dataclass + immutable update 即可。
"""

from orion_agent.state.app_state import (
    AppState,
    IDEContext,
    ToolPermissionContext,
)

__all__ = [
    "AppState",
    "IDEContext",
    "ToolPermissionContext",
]
