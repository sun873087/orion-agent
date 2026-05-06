"""AgentContext — 取代 TS bootstrap/state.ts 全域狀態。

設計決策:**不要** module-level mutable state。改用 dataclass 傳遞,
測試與並行隔離都更乾淨。每個 conversation 一個 AgentContext。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4

import anyio


@dataclass
class TokenBudget:
    """Token 預算追蹤。對應 TS query/tokenBudget.ts。"""

    max_input_tokens: int = 200_000
    max_output_tokens: int = 8_192
    used_input_tokens: int = 0
    used_output_tokens: int = 0


@dataclass
class AgentContext:
    """傳遞給整個 agent loop 的執行 context。

    每個 conversation 一個 AgentContext。子 agent / fork 各有自己的。
    取代 TS bootstrap/state.ts(那是 module-level 全域)。
    """

    session_id: UUID = field(default_factory=uuid4)
    cwd: Path = field(default_factory=Path.cwd)
    abort_event: anyio.Event = field(default_factory=anyio.Event)
    token_budget: TokenBudget = field(default_factory=TokenBudget)
    feature_flags: dict[str, bool] = field(default_factory=dict)
    # 後續 phase 加入:sandbox, permissions, hooks, plan_mode_state 等

    def feature(self, name: str) -> bool:
        """對應 TS 的 feature() 函式。

        Python 沒有 build-time DCE,直接 runtime 查表。
        """
        return self.feature_flags.get(name, False)
