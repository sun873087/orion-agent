"""Token estimation。對應 TS services/tokenEstimation.ts。

兩階段策略:
1. **rough**:`len(text) / 4`(快、粗,英文 ~ 1 char ≈ 0.25 token,CJK ~1 char ≈ 1 token)
2. **precise**:caller 提供 callback(通常 wrap Anthropic `count_tokens` API),只在
   rough 接近 threshold 才呼,避免每次 API call。

application:
- memory selector — 估字串大小決定要不要進 retrieval
- mcpValidation — MCP tool result 超 threshold 才需要 truncate
- input — 大文字 attachment 估值

不依賴 Anthropic SDK(避免循環);caller 自己接 provider.count_tokens 之類。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

_DEFAULT_TWO_PHASE_FACTOR = 0.5
"""rough estimate ≤ threshold * factor → 確定不超(便宜路徑,跳過 precise)。

對應 TS `MCP_TOKEN_COUNT_THRESHOLD_FACTOR = 0.5`。
"""

# CJK / 拉丁字符的字元寬度差異:CJK 約 1 char/token;拉丁約 4 char/token
_CJK_THRESHOLD = 0x3000 # 大致 CJK / 全形開始


def rough_token_count(text: str) -> int:
    """快速 token 估算(無 API call)。

    經驗值:
    - 拉丁字 ≈ 4 char/token
    - CJK ≈ 1 char/token

    本函式檢測「至少含 1 個 CJK / 全形字符」就走 1 char/token 路徑(保守高估)。
    純拉丁(英 / 程式碼)走 4 char/token。
    """
    if not text:
        return 0
    has_cjk = any(ord(c) >= _CJK_THRESHOLD for c in text)
    return len(text) if has_cjk else max(1, len(text) // 4)


def rough_messages_token_count(messages: list[dict[str, Any]]) -> int:
    """估 messages list 的總 token(role + content 各算)。

    messages 是 caller-provided dict list(對應 Anthropic API messages 格式)。
    content 可能是 str 或 list[ContentBlock dict]。
    """
    total = 0
    for m in messages:
        role = m.get("role", "")
        total += rough_token_count(role)
        c = m.get("content", "")
        if isinstance(c, str):
            total += rough_token_count(c)
        elif isinstance(c, list):
            for block in c:
                if not isinstance(block, dict):
                    continue
                t = block.get("text") or block.get("content") or ""
                if isinstance(t, str):
                    total += rough_token_count(t)
        # 每 message 加 4 token overhead(對應 OpenAI / Anthropic message envelope)
        total += 4
    return total


PreciseCounter = Callable[[list[dict[str, Any]]], Awaitable[int]]
"""async function:回精準 token 數。caller 通常 wrap provider.count_tokens。"""


async def estimate_with_two_phase(
    messages: list[dict[str, Any]],
    *,
    threshold: int,
    precise_counter: PreciseCounter | None = None,
    factor: float = _DEFAULT_TWO_PHASE_FACTOR,
) -> tuple[int, bool]:
    """兩階段判斷:tokens 是否超過 threshold。

    Args:
        messages: messages list
        threshold: token 閾值
        precise_counter: 精準 count callback;None → 永遠用 rough(粗)
        factor: rough 跳過 precise 的折扣(0-1)。預設 0.5,對應 TS。

    Returns:
        (estimate, exceeds_threshold)
        estimate 是用過的最終估值(可能是 rough 也可能是 precise)。
    """
    rough = rough_messages_token_count(messages)

    # 確定不超(rough 已 << threshold)
    if rough <= threshold * factor:
        return rough, False

    # 確定超(rough 已 > threshold)
    if rough > threshold:
        return rough, True

    # 灰色地帶 — 才呼 precise
    if precise_counter is None:
        # 沒 counter,保守用 rough
        return rough, rough > threshold
    try:
        precise = await precise_counter(messages)
    except Exception: # noqa: BLE001 — counter 失敗 fallback rough
        return rough, rough > threshold
    return precise, precise > threshold
