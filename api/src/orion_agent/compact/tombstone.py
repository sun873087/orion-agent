"""Tombstone helpers — 把 messages 範圍替換成 TombstoneBlock。

對應 spec § 5 snip.py。

TombstoneBlock 本身定義在 `llm/types.py`(因為它是 ContentBlock 的成員)。
本檔只提供操作 helper。
"""

from __future__ import annotations

from datetime import UTC, datetime

from orion_agent.llm.types import (
    NormalizedMessage,
    TombstoneBlock,
)


def replace_range_with_tombstone(
    messages: list[NormalizedMessage],
    *,
    start: int,
    end: int,
    summary: str,
    original_token_count: int,
) -> list[NormalizedMessage]:
    """把 `messages[start:end+1]` 替換成單一 user role TombstoneBlock 訊息。

    Args:
        messages: 原 conversation messages
        start: inclusive 起始 index
        end: inclusive 結束 index
        summary: LLM 生成的摘要
        original_token_count: 被壓縮前的概略 token 數(供 telemetry)

    Returns:
        新 messages list(原資料不動 — pure function)
    """
    if start < 0 or end >= len(messages) or start > end:
        raise ValueError(
            f"invalid tombstone range: start={start}, end={end}, "
            f"len={len(messages)}"
        )

    tombstone = TombstoneBlock(
        summary=summary,
        range_start_msg_index=start,
        range_end_msg_index=end,
        original_token_count=original_token_count,
        captured_at=datetime.now(UTC).isoformat(),
    )

    new_messages: list[NormalizedMessage] = list(messages[:start])
    new_messages.append(
        NormalizedMessage(role="user", content=[tombstone]),
    )
    new_messages.extend(messages[end + 1 :])
    return new_messages
