"""AutoCompact — 主動 token budget 檢查 + 觸發摘要。

對應 spec § 5 auto.py。

每 turn 進 API 前 check:若估計 token 數 > threshold * max_context,觸發 strategy
摘要前 50% messages,把那段替換成 TombstoneBlock。
"""

from __future__ import annotations

import os

from orion_agent.compact.strategies import (
    CompactionStrategy,
    SonnetSummaryStrategy,
    TruncateStrategy,
)
from orion_agent.compact.tombstone import replace_range_with_tombstone
from orion_model.provider import LLMProvider
from orion_model.types import (
    NormalizedMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)

AUTO_COMPACT_THRESHOLD_DEFAULT = 0.8
"""預設觸發比例 — 撞到 max_context * 0.8 就 compact。"""

AUTO_COMPACT_RANGE_RATIO = 0.5
"""被壓縮的範圍比例 — 前 50% messages 進 tombstone。"""


def _get_threshold() -> float:
    raw = os.environ.get("ORION_AUTO_COMPACT_THRESHOLD")
    if not raw:
        return AUTO_COMPACT_THRESHOLD_DEFAULT
    try:
        v = float(raw)
        if 0.1 <= v <= 0.99:
            return v
    except ValueError:
        pass
    return AUTO_COMPACT_THRESHOLD_DEFAULT


def estimate_token_count(messages: list[NormalizedMessage]) -> int:
    """概略 token 估算。1 token ≈ 4 chars(英文 / 中文混雜的偏保守值)。"""
    total_chars = 0
    for m in messages:
        if isinstance(m.content, str):
            total_chars += len(m.content)
            continue
        if not isinstance(m.content, list):
            continue
        for block in m.content:
            if isinstance(block, TextBlock):
                total_chars += len(block.text)
            elif isinstance(block, ToolUseBlock):
                total_chars += len(block.name) + len(str(block.input))
            elif isinstance(block, ToolResultBlock):
                content = block.content
                total_chars += (
                    len(content) if isinstance(content, str) else len(str(content))
                )
            else:
                # ImageBlock / ThinkingBlock / TombstoneBlock — 估 100 chars 過去
                total_chars += 100
    return total_chars // 4


async def auto_compact_if_needed(
    messages: list[NormalizedMessage],
    *,
    provider: LLMProvider,
    strategy: CompactionStrategy | None = None,
) -> tuple[list[NormalizedMessage], bool]:
    """進 API 前檢查並可能 compact。

    Args:
        messages: 當前 state_messages
        provider: 用 capabilities.max_context_tokens + 給 strategy 摘要用
        strategy: 預設 SonnetSummaryStrategy,可注入 TruncateStrategy 給測試

    Returns:
        (new_messages, was_compacted):若無需 compact,new_messages 原樣回 + False
    """
    if len(messages) < 4:
        # 太少 messages 沒意義 compact
        return messages, False

    threshold = _get_threshold()
    max_context = provider.capabilities.max_context_tokens
    used = estimate_token_count(messages)

    if used < int(max_context * threshold):
        return messages, False

    # 需要 compact:選前 50%(從 index 0 起算)
    cutoff = max(2, int(len(messages) * AUTO_COMPACT_RANGE_RATIO))
    # 確保 cutoff 不切到「assistant 後面跟著的 tool_result」中間
    cutoff = _adjust_cutoff_to_safe_boundary(messages, cutoff)
    if cutoff < 1:
        return messages, False

    strat = strategy or SonnetSummaryStrategy()
    try:
        summary = await strat.summarize(messages[:cutoff], provider=provider)
    except Exception:  # noqa: BLE001 — 摘要失敗 fallback truncate
        summary = TruncateStrategy().summarize_sync(messages[:cutoff])

    pre_chunk = messages[:cutoff]
    pre_token_estimate = estimate_token_count(pre_chunk)

    new_messages = replace_range_with_tombstone(
        messages,
        start=0,
        end=cutoff - 1,
        summary=summary,
        original_token_count=pre_token_estimate,
    )
    return new_messages, True


def _adjust_cutoff_to_safe_boundary(
    messages: list[NormalizedMessage],
    cutoff: int,
) -> int:
    """避免把一個 assistant tool_use 跟它後面的 tool_result 切開。

    若 messages[cutoff-1] 是 assistant 含 ToolUseBlock,且 messages[cutoff] 是
    user 含 ToolResultBlock — 把 cutoff 往後推一格(連同 tool_result 一起被壓)。
    """
    if cutoff < 1 or cutoff >= len(messages):
        return cutoff

    last = messages[cutoff - 1]
    nxt = messages[cutoff]

    last_has_tool_use = (
        last.role == "assistant"
        and isinstance(last.content, list)
        and any(isinstance(b, ToolUseBlock) for b in last.content)
    )
    next_has_tool_result = (
        nxt.role == "user"
        and isinstance(nxt.content, list)
        and any(isinstance(b, ToolResultBlock) for b in nxt.content)
    )

    if last_has_tool_use and next_has_tool_result:
        return cutoff + 1
    return cutoff
