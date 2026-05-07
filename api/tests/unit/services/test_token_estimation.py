"""rough_token_count + estimate_with_two_phase。"""

from __future__ import annotations

from typing import Any

import pytest

from orion_agent.services.token_estimation import (
    estimate_with_two_phase,
    rough_messages_token_count,
    rough_token_count,
)


def test_rough_empty() -> None:
    assert rough_token_count("") == 0


def test_rough_latin_chars_per_4() -> None:
    # 100 char ASCII → 25 token rough
    assert rough_token_count("a" * 100) == 25


def test_rough_cjk_chars_per_1() -> None:
    # 含 CJK → 1 char/token(保守高估)
    assert rough_token_count("你好世界") == 4
    # 混雜也走 CJK 路徑(保守)
    mixed = "hello 你好"
    assert rough_token_count(mixed) == len(mixed)


def test_rough_messages_includes_overhead() -> None:
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    n = rough_messages_token_count(msgs)
    # 4 char "user"/4=1 + 2 char "hi"/4=0 (max 1) + envelope 4 + 9 char "assistant"/4=2 + ... + envelope 4
    assert n > 4 * 2  # envelope at least


def test_rough_messages_handles_content_blocks() -> None:
    msgs = [
        {"role": "user", "content": [{"type": "text", "text": "hello world there"}]},
    ]
    n = rough_messages_token_count(msgs)
    assert n > 0


@pytest.mark.asyncio
async def test_two_phase_below_factor_skips_precise() -> None:
    msgs = [{"role": "user", "content": "tiny"}]
    called: list[bool] = []

    async def precise(_msgs: list[Any]) -> int:
        called.append(True)
        return 999

    estimate, exceeds = await estimate_with_two_phase(
        msgs, threshold=1000, precise_counter=precise,
    )
    # rough 很小 ≤ 1000 * 0.5 → 不呼 precise
    assert called == []
    assert exceeds is False
    assert estimate < 100


@pytest.mark.asyncio
async def test_two_phase_above_threshold_skips_precise() -> None:
    big_text = "x" * 100_000  # rough ~25000
    msgs = [{"role": "user", "content": big_text}]
    called: list[bool] = []

    async def precise(_msgs: list[Any]) -> int:
        called.append(True)
        return 24_999

    estimate, exceeds = await estimate_with_two_phase(
        msgs, threshold=1000, precise_counter=precise,
    )
    # rough 已遠超 threshold,不需要 precise
    assert called == []
    assert exceeds is True
    assert estimate > 1000


@pytest.mark.asyncio
async def test_two_phase_grey_zone_calls_precise() -> None:
    msgs = [{"role": "user", "content": "x" * 6000}]  # rough = 1500
    called: list[bool] = []

    async def precise(_msgs: list[Any]) -> int:
        called.append(True)
        return 1100

    estimate, exceeds = await estimate_with_two_phase(
        msgs, threshold=2000, precise_counter=precise,
    )
    # rough = 1500 在 [2000*0.5=1000, 2000] 灰色地帶 → 呼 precise
    assert called == [True]
    assert estimate == 1100
    assert exceeds is False  # precise 1100 < 2000


@pytest.mark.asyncio
async def test_two_phase_no_counter_falls_back() -> None:
    msgs = [{"role": "user", "content": "x" * 6000}]
    estimate, exceeds = await estimate_with_two_phase(
        msgs, threshold=2000, precise_counter=None,
    )
    # 沒 counter,用 rough 判定
    assert estimate > 0


@pytest.mark.asyncio
async def test_two_phase_precise_failure_falls_back() -> None:
    msgs = [{"role": "user", "content": "x" * 6000}]

    async def crash(_msgs: list[Any]) -> int:
        raise RuntimeError("API down")

    estimate, exceeds = await estimate_with_two_phase(
        msgs, threshold=2000, precise_counter=crash,
    )
    # precise 失敗 → fallback rough
    assert estimate > 0
