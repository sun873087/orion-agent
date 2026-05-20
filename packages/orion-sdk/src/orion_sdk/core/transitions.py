"""query loop 的狀態轉換型別。對應 TS Claude Code `src/query/transitions.ts`。

query_loop 一輪結束後決定下一步:Continue 再跑 / Terminal 結束。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Continue:
    """要繼續(剛執行完工具,結果已回填,該再請求模型)。"""

    reason: str
    """例:'tool_results' / 'initial' / 'auto_compact'。"""


@dataclass
class Terminal:
    """query loop 結束。"""

    reason: str = "natural_stop"
    """常見值:
    - natural_stop:模型本輪沒 emit tool_use,自然完成
    - max_turns_reached:超過 max_turns 強制終止
    - aborted:ctx.abort_event 被觸發
    - error:loop 內部 raise(API 錯誤、unrecoverable)
    """


Transition = Continue | Terminal
