"""Compaction — 控制 conversation 不爆 context window。

兩種模式:
- **autoCompact**:每 turn 進 API 前主動檢查 token budget,接近上限才壓
- **reactive**:catch prompt-too-long 錯誤,強制壓 + retry once

兩者最終都把舊 messages 替換成 TombstoneBlock(`llm/types.py:TombstoneBlock`)。
"""

from orion_sdk.compact.auto import (
    AUTO_COMPACT_THRESHOLD_DEFAULT,
    auto_compact_if_needed,
    estimate_token_count,
)
from orion_sdk.compact.reactive import (
    is_prompt_too_long_error,
    reactive_compact,
)
from orion_sdk.compact.strategies import (
    CompactionStrategy,
    SonnetSummaryStrategy,
    TruncateStrategy,
)
from orion_sdk.compact.tombstone import (
    replace_range_with_tombstone,
)

__all__ = [
    "AUTO_COMPACT_THRESHOLD_DEFAULT",
    "CompactionStrategy",
    "SonnetSummaryStrategy",
    "TruncateStrategy",
    "auto_compact_if_needed",
    "estimate_token_count",
    "is_prompt_too_long_error",
    "reactive_compact",
    "replace_range_with_tombstone",
]
