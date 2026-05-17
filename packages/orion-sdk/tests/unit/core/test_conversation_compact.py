"""Conversation.compact() — manual + auto 路徑。"""

from __future__ import annotations

import pytest

from orion_sdk.compact.strategies import TruncateStrategy
from orion_sdk.core.conversation import CompactResult, Conversation
from orion_sdk._testing import MockProvider
from orion_model.types import (
    NormalizedMessage,
    TombstoneBlock,
    ToolResultBlock,
    ToolUseBlock,
)


def _msgs(n: int) -> list[NormalizedMessage]:
    out: list[NormalizedMessage] = []
    for i in range(n):
        out.append(NormalizedMessage(role="user", content=f"u{i}: " + "x" * 100))
        out.append(NormalizedMessage(role="assistant", content=f"a{i}: " + "y" * 100))
    return out


@pytest.mark.asyncio
async def test_compact_force_true_compacts_short_history(monkeypatch) -> None:  # noqa: ANN001
    """force=True 即使沒爆 threshold 也應該壓。"""
    # SonnetSummaryStrategy 會打 provider — mock 它 fallback 到 TruncateStrategy
    # 透過讓 stream 拋例外做到
    monkeypatch.delenv("ORION_AUTO_COMPACT_THRESHOLD", raising=False)
    provider = MockProvider(turns=[])  # 沒 turn → 沒 LLM response,fallback truncate
    conv = Conversation(
        provider=provider,  # type: ignore[arg-type]
        persistence_enabled=False,
    )
    conv.state_messages = _msgs(4)  # 8 messages
    original_count = len(conv.state_messages)

    result = await conv.compact(force=True)

    assert isinstance(result, CompactResult)
    assert result.was_compacted is True
    assert result.summary  # 有內容
    assert result.kept_message_count < original_count
    assert len(conv.state_messages) == result.kept_message_count
    # 第一張現在是 tombstone
    first = conv.state_messages[0]
    assert isinstance(first.content, list)
    assert isinstance(first.content[0], TombstoneBlock)


@pytest.mark.asyncio
async def test_compact_force_false_skips_under_threshold(monkeypatch) -> None:  # noqa: ANN001
    """auto 模式下 token 沒爆,不該壓。"""
    monkeypatch.delenv("ORION_AUTO_COMPACT_THRESHOLD", raising=False)
    provider = MockProvider(turns=[])
    conv = Conversation(
        provider=provider,  # type: ignore[arg-type]
        persistence_enabled=False,
    )
    conv.state_messages = _msgs(4)
    before = list(conv.state_messages)

    result = await conv.compact(force=False)

    assert result.was_compacted is False
    assert result.summary == ""
    assert conv.state_messages == before


@pytest.mark.asyncio
async def test_compact_too_few_messages_noop() -> None:
    """state_messages < 2 一律不壓。"""
    provider = MockProvider(turns=[])
    conv = Conversation(
        provider=provider,  # type: ignore[arg-type]
        persistence_enabled=False,
    )
    conv.state_messages = [NormalizedMessage(role="user", content="hi")]

    result = await conv.compact(force=True)

    assert result.was_compacted is False
    assert result.kept_message_count == 1


@pytest.mark.asyncio
async def test_compact_threshold_field_overrides_env(monkeypatch) -> None:  # noqa: ANN001
    """conv.auto_compact_threshold 應傳到 auto_compact_if_needed。"""
    monkeypatch.setenv("ORION_AUTO_COMPACT_THRESHOLD", "0.1")  # env 會觸發
    provider = MockProvider(turns=[])
    conv = Conversation(
        provider=provider,  # type: ignore[arg-type]
        persistence_enabled=False,
    )
    conv.state_messages = _msgs(10)
    conv.auto_compact_threshold = 0.99  # 99% 不該觸發

    result = await conv.compact(force=False)

    assert result.was_compacted is False


@pytest.mark.asyncio
async def test_compact_clears_replacement_state(monkeypatch) -> None:  # noqa: ANN001
    """壓縮後 replacement_state 應清掉(舊 tool_use_id 失效)。"""
    monkeypatch.delenv("ORION_AUTO_COMPACT_THRESHOLD", raising=False)
    provider = MockProvider(turns=[])
    conv = Conversation(
        provider=provider,  # type: ignore[arg-type]
        persistence_enabled=False,
    )
    conv.state_messages = _msgs(4)
    conv.replacement_state.seen_ids.add("old-tool-use-1")
    conv.replacement_state.replacements["old-tool-use-2"] = "preview text"

    await conv.compact(force=True)

    assert len(conv.replacement_state.seen_ids) == 0
    assert len(conv.replacement_state.replacements) == 0
