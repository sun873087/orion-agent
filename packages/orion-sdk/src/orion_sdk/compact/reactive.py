"""Reactive compaction — provider 回 prompt-too-long 時急救。

對應 spec § 5 reactive.py。

流程:
  query_loop 在呼 provider.stream 時 catch exception
  → 若是 prompt-too-long 類錯,call reactive_compact(force=True 觸發 compact 不檢 threshold)
  → retry once
  → 還失敗 → raise

**只 retry 一次**(spec 明確要求),避免無限迴圈。
"""

from __future__ import annotations

from orion_sdk.compact.auto import auto_compact_if_needed
from orion_sdk.compact.strategies import SonnetSummaryStrategy
from orion_sdk.compact.tombstone import replace_range_with_tombstone
from orion_model.provider import LLMProvider
from orion_model.types import NormalizedMessage

_PROMPT_TOO_LONG_KEYWORDS = (
    "prompt is too long",
    "context length",
    "context_length_exceeded",
    "input is too long",
    "max_tokens_to_sample",
    "string_above_max_length",
)


def is_prompt_too_long_error(exc: Exception) -> bool:
    """偵測 provider 回的 prompt-too-long 錯。

    Anthropic 與 OpenAI 訊息格式不同,用關鍵字判斷:
    - Anthropic: "prompt is too long" / "context length"
    - OpenAI: "context_length_exceeded" / "string_above_max_length"
    """
    msg = str(exc).lower()
    return any(k in msg for k in _PROMPT_TOO_LONG_KEYWORDS)


async def reactive_compact(
    messages: list[NormalizedMessage],
    *,
    provider: LLMProvider,
    aggressive_ratio: float = 0.7,
) -> list[NormalizedMessage]:
    """強制壓縮 — 不看 threshold,前 aggressive_ratio 一律 compact。

    比 autoCompact 更兇:預設壓 70%(autoCompact 是 50%),
    因為 reactive 已經撞到 token 上限,要更狠才能 retry 過。
    """
    if len(messages) < 4:
        return messages

    cutoff = max(2, int(len(messages) * aggressive_ratio))
    if cutoff >= len(messages):
        cutoff = len(messages) - 1

    # 先試 LLM summary
    try:
        summary = await SonnetSummaryStrategy().summarize(
            messages[:cutoff], provider=provider,
        )
    except Exception:  # noqa: BLE001
        # 用簡易截斷
        summary = (
            f"[Earlier conversation force-truncated due to context overflow: "
            f"{cutoff} messages elided.]"
        )

    from orion_sdk.compact.auto import estimate_token_count

    return replace_range_with_tombstone(
        messages,
        start=0,
        end=cutoff - 1,
        summary=summary,
        original_token_count=estimate_token_count(messages[:cutoff]),
    )


# 維持 import 連結,避免 lint
_ = auto_compact_if_needed
