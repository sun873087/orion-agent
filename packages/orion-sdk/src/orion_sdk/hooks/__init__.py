"""Hooks — 可註冊 PreToolUse / PostToolUse callback。

範圍:基礎 registry + 兩種 event(PreToolUse / PostToolUse)。
會擴成完整 8 種 event(SessionStart / UserPromptSubmit / Stop / SubagentStop / Notification / PreCompact)。
"""

from orion_sdk.hooks.events import (
    HookEvent,
    PostToolUseEvent,
    PreToolUseEvent,
)
from orion_sdk.hooks.registry import (
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
