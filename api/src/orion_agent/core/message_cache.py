"""Messages 層的 cache breakpoint 策略 — Stage 3 rolling cache。

System prompt 已用 2 個 bp(static + session_stable),Anthropic 限 4 個,
所以 messages 最多剩 2 個 bp。

策略:
- bp #1 = 最後一個 message(current user message,frozen with per-turn injection)
        → 寫入此 turn 的 cache,供下 turn 讀取
- bp #2 = 倒數第二個 user message(上 turn 的 user input)
        → 讀取上 turn 寫入的 cache(prefix 不變,hit)

每 turn 滾動,長對話 cache hit rate 接近 100%(只有當前 turn 的新 content
要付 1.25x 寫入,過去全部 0.1x 讀取)。
"""

from __future__ import annotations

from orion_model.types import NormalizedMessage


def compute_message_breakpoints(messages: list[NormalizedMessage]) -> list[int]:
    """回傳 messages indices 列表,在每個 index 標 cache_control。

    Returns:
        最多 2 個 index:[最後 user msg 之前的 user msg, 最後 message]
        若 messages 短於需要,回較少 index。空 list → 回 []。

    Examples:
        - [u1] → [0](單 user msg,寫一次 cache)
        - [u1, a1, u2] → [0, 2](u1 上 turn 寫過,可 hit;u2 寫新)
        - [u1, a1, u2, a2, u3] → [2, 4](u2 上 turn 寫過,u3 寫新)
    """
    n = len(messages)
    if n == 0:
        return []
    bps = [n - 1]  # 最後一個 message,永遠 bp
    # 從尾巴往前找上一個 user message(跳過當前 user msg 自己)
    for i in range(n - 2, -1, -1):
        if messages[i].role == "user":
            bps.append(i)
            break
    return sorted(bps)
