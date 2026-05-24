"""Phase 11 — follow-up 建議 side-query。

UI(chips)由 WS follow_ups_updated 驅動,turn-dependent(mock 空 turn 無法 e2e),
這裡測產生 + 解析邏輯。
"""

from __future__ import annotations

import pytest

from orion_chat_api.title_gen import generate_followups


@pytest.mark.asyncio
async def test_generate_followups_parses_lines() -> None:
    from orion_sdk._testing import MockProvider, MockTurn

    mp = MockProvider(
        turns=[MockTurn(text="1. What next?\n- How about X?\nTell me more?")],
    )
    out = await generate_followups(mp, "hi", "answer")
    assert out == ["What next?", "How about X?", "Tell me more?"]


@pytest.mark.asyncio
async def test_generate_followups_caps_at_three() -> None:
    from orion_sdk._testing import MockProvider, MockTurn

    mp = MockProvider(turns=[MockTurn(text="a\nb\nc\nd\ne")])
    assert len(await generate_followups(mp, "u", "a")) == 3


@pytest.mark.asyncio
async def test_generate_followups_empty() -> None:
    from orion_sdk._testing import MockProvider

    assert await generate_followups(MockProvider(turns=[]), "u", "a") == []
