"""Hooks — 可註冊 PreToolUse / PostToolUse callback。

Phase 1 範圍:基礎 registry + 兩種 event(PreToolUse / PostToolUse)。
Phase 8 會擴成完整 8 種 event(SessionStart / UserPromptSubmit / Stop / SubagentStop / Notification / PreCompact)。
"""

from orion_agent.hooks.events import (
    HookEvent,
    PostToolUseEvent,
    PreToolUseEvent,
)
from orion_agent.hooks.registry import (
    HookCallback,
    HookRegistry,
)

__all__ = [
    "HookCallback",
    "HookEvent",
    "HookRegistry",
    "PostToolUseEvent",
    "PreToolUseEvent",
]
