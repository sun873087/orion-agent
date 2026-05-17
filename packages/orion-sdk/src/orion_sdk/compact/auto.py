"""AutoCompact — 主動 token budget 檢查 + 觸發摘要。

對應 spec § 5 auto.py。

每 turn 進 API 前 check:若估計 token 數 > threshold * max_context,觸發 strategy
摘要前 50% messages,把那段替換成 TombstoneBlock。
"""

from __future__ import annotations

import os

from orion_sdk.compact.strategies import (
    CompactionStrategy,
    SonnetSummaryStrategy,
    TruncateStrategy,
)
from orion_sdk.compact.tombstone import replace_range_with_tombstone
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


def _clamp_threshold(value: float) -> float:
    if value < 0.1:
        return 0.1
    if value > 0.99:
        return 0.99
    return value


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
    threshold: float | None = None,
    locale: str | None = None,
    summary_provider: LLMProvider | None = None,
) -> tuple[list[NormalizedMessage], bool]:
    """進 API 前檢查並可能 compact。

    Args:
        messages: 當前 state_messages
        provider: 用 capabilities.max_context_tokens 做 threshold 判斷
            (這該是 chat model 的 context window,不是 summary model 的)
        strategy: 預設 SonnetSummaryStrategy,可注入 TruncateStrategy 給測試
        threshold: 觸發比例,優先於 ORION_AUTO_COMPACT_THRESHOLD env。
            傳 None → 用 env / 預設 0.8。
        locale: 摘要要用的語系
        summary_provider: 摘要 LLM call 用的 provider。None → 用 `provider`
            (跟 chat 同一個);通常 caller 注入便宜 model(Haiku / 4o-mini)
            把 compact cost 降下來

    Returns:
        (new_messages, was_compacted):若無需 compact,new_messages 原樣回 + False
    """
    if len(messages) < 4:
        # 太少 messages 沒意義 compact
        return messages, False

    eff_threshold = _clamp_threshold(threshold) if threshold is not None else _get_threshold()
    max_context = provider.capabilities.max_context_tokens
    used = estimate_token_count(messages)

    if used < int(max_context * eff_threshold):
        return messages, False

    return await compact_messages_now(
        messages,
        provider=summary_provider or provider,
        strategy=strategy,
        locale=locale,
    ), True


async def compact_messages_now(
    messages: list[NormalizedMessage],
    *,
    provider: LLMProvider,
    strategy: CompactionStrategy | None = None,
    range_ratio: float = AUTO_COMPACT_RANGE_RATIO,
    locale: str | None = None,
) -> list[NormalizedMessage]:
    """強制壓縮(跳過 threshold 檢查)— 給手動 /compact 用。

    Messages < 2 直接回原 list(沒東西可壓)。Cutoff 同樣會被
    `_adjust_cutoff_to_safe_boundary` 校正,避免切到 tool_use/tool_result 配對。
    """
    if len(messages) < 2:
        return messages

    cutoff = max(2, int(len(messages) * range_ratio))
    cutoff = _adjust_cutoff_to_safe_boundary(messages, cutoff)
    if cutoff < 1 or cutoff >= len(messages):
        # 全壓也不對(沒人說話的 assistant 卡在最後),保守不動
        return messages

    strat = strategy or SonnetSummaryStrategy()
    try:
        summary = await strat.summarize(messages[:cutoff], provider=provider, locale=locale)
    except Exception:  # noqa: BLE001 — 摘要失敗 fallback truncate
        summary = TruncateStrategy().summarize_sync(messages[:cutoff])

    pre_token_estimate = estimate_token_count(messages[:cutoff])
    return replace_range_with_tombstone(
        messages,
        start=0,
        end=cutoff - 1,
        summary=summary,
        original_token_count=pre_token_estimate,
    )


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
