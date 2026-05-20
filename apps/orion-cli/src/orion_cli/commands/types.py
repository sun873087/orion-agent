"""Command Protocol。對應 TS Command interface。

Slash command 不只是 alias — 可以 mutate conversation state(/clear 清訊息),
或注入 prompt(/init 把分析 prompt 灌進主對話)。

Result 物件四個欄位描述「該怎麼處理」:
- `text`:純顯示給 user(不送 API)
- `new_user_message`:轉成 user message 進 query loop(例 /init)
- `inject_into_prompt`:注入下次 system prompt(例 /memory 載入記憶)
- `side_effect`:純描述,例 "cleared 12 messages"
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class CommandResult:
    """命令執行結果。"""

    text: str | None = None
    """要顯示給使用者的純文字(UI 顯示,不送 API)。"""

    new_user_message: str | None = None
    """轉成 user message 進 conversation(例 /init 把分析 prompt 灌進去)。"""

    inject_into_prompt: str | None = None
    """注入到下次 system prompt(例 /memory 把記憶塞進去)。"""

    side_effect: str | None = None
    """side effect 描述(已執行的動作,給 telemetry / log)。"""


@runtime_checkable
class Command(Protocol):
    """Slash 命令介面。"""

    name: str
    """命令名稱(不含 / 前綴)。"""

    description: str
    """help 顯示用。"""

    async def execute(
        self,
        args: str,
        ctx: Any,
        conversation: Any,
    ) -> CommandResult:
        """執行命令。

        Args:
            args: `/cmd` 後面的參數字串(已 strip)
            ctx: AgentContext
            conversation: Conversation instance(可 mutate state)
        """
        ...
