"""Input pipeline — Phase 11。

主協調器 `process_user_input`,把 raw input 轉為 Conversation 可消化的事件:
- slash command → CommandResult / 注入 user message
- 純文字 + image attachments → ContentBlock list

Phase 11 範圍:
- ✅ slash registry + 2 內建(/help / /model)
- ✅ image attachments(base64 → ContentBlock)
- ✅ 上傳檔附件(Phase 6 WebSocket UserMessageEvent.attachments)
- ❌ `!shell` 直接執行(SaaS 危險,Phase 11c)
- ❌ `@file` ref(由 upload 取代)
"""

from __future__ import annotations

from orion_agent.input.process_input import (
    InputEvent,
    UserMessageEvent,
    process_user_input,
)
from orion_agent.input.slash import is_slash_command, parse_slash

__all__ = [
    "InputEvent",
    "UserMessageEvent",
    "is_slash_command",
    "parse_slash",
    "process_user_input",
]
