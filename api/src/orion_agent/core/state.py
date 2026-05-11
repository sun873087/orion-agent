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

    # ─── Phase 1 加入 ─────────────────────────────────────────────────────
    todos: list[dict[str, str]] = field(default_factory=list)
    """TodoWriteTool 的 in-memory list。每筆 dict 至少含 'content' 與 'status'。"""

    sub_agent_depth: int = 0
    """AgentTool spawn 出的子 agent 深度。0 = 主 agent,1 = 子,>=2 禁止再 spawn。"""

    # ─── Phase 2 加入 ─────────────────────────────────────────────────────
    replacement_state: object | None = None
    """ContentReplacementState(避免循環 import,這裡用 object)。
    Conversation 在跨 turn 時持續累積決策。query_loop 每 turn 進 API 前會 apply_tool_result_budget。
    None 表示「尚未啟用第 3 層 budget」(子 agent / 測試)。
    """

    # ─── Phase 3 加入 ─────────────────────────────────────────────────────
    user_id: str = "default"
    """Per-user memory key。CLI 預設 "default";Phase 6 FastAPI 透過 session middleware 注入。"""

    # ─── Phase 9 加入 ─────────────────────────────────────────────────────
    cwd_stack: list[Path] = field(default_factory=list)
    """EnterWorkdirTool / ExitWorkdirTool 的 cwd push/pop 堆疊。
    Enter 把當前 ctx.cwd push 進來,改成新值;Exit 從 stack pop 還原。
    """

    # ─── Phase 7 加入 ─────────────────────────────────────────────────────
    sandbox_backend: object | None = None
    """SandboxBackend instance(避免循環 import,型別 object)。
    Conversation.send() 會把自己持有的 backend 注進來;tools 可透過 ctx.sandbox_backend 動態取用。
    None = 走 host(LocalBackend 同效)。"""

    # ─── Phase 12 加入 ────────────────────────────────────────────────────
    plan_mode_state: object | None = None
    """PlanModeState instance(避免循環 import,型別 object)。
    None → 視同 INACTIVE(plan mode 未啟用)。EnterPlanModeTool / ExitPlanModeTool
    會 mutate 此欄位。permissions 走 plan_mode_aware wrapper 會檢查狀態。"""

    file_state_cache: object | None = None
    """FileStateCache instance(同上,避免循環 import)。
    Read 後 record_read,Edit / Write 前檢查 has_been_read + is_stale。
    None → 不啟用 staleness check(向後相容,Phase 11 之前行為)。"""

    app_state: object | None = None
    """AppState instance(同上)。Conversation 層級的廣義應用狀態(權限歷史、IDE
    context、MCP server 狀態等)。Phase 12 抽象,後續 phase 才大量使用。"""

    # ─── Phase 18 加入 ────────────────────────────────────────────────────
    url_cache: object | None = None
    """UrlCache instance(storage/url_cache.py,object 避免循環 import)。
    WebFetchTool 首次 fetch 時 lazy init。同 session 內反覆 fetch 同 URL 走 cache。"""

    def feature(self, name: str) -> bool:
        """對應 TS 的 feature() 函式。

        Python 沒有 build-time DCE,直接 runtime 查表。
        """
        return self.feature_flags.get(name, False)
