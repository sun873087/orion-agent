"""prompt/sections.py — section cache 行為。"""

from __future__ import annotations

import pytest

from orion_agent.prompt.sections import (
    DANGEROUS_uncached,
    clear_section_cache,
    register_section,
    section_cache_size,
)


@pytest.fixture(autouse=True)
def clear_cache_each_test() -> None:
    clear_section_cache()


@pytest.mark.asyncio
async def test_first_call_computes_and_caches() -> None:
    call_count = 0

    async def builder() -> str:
        nonlocal call_count
        call_count += 1
        return "computed_value"

    result = await register_section("k1", builder)
    assert result == "computed_value"
    assert call_count == 1
    assert section_cache_size() == 1


@pytest.mark.asyncio
async def test_second_call_uses_cache() -> None:
    call_count = 0

    async def builder() -> str:
        nonlocal call_count
        call_count += 1
        return "v"

    await register_section("k1", builder)
    await register_section("k1", builder)
    await register_section("k1", builder)
    assert call_count == 1  # 只算一次


@pytest.mark.asyncio
async def test_different_keys_different_cache() -> None:
    call_count = 0

    async def builder() -> str:
        nonlocal call_count
        call_count += 1
        return f"v{call_count}"

    await register_section("k1", builder)
    await register_section("k2", builder)
    assert call_count == 2
    assert section_cache_size() == 2


@pytest.mark.asyncio
async def test_dangerous_uncached_skips_cache() -> None:
    call_count = 0

    async def builder() -> str:
        nonlocal call_count
        call_count += 1
        return "x"

    await register_section(DANGEROUS_uncached, builder)
    await register_section(DANGEROUS_uncached, builder)
    assert call_count == 2  # 每次都算
    assert section_cache_size() == 0


@pytest.mark.asyncio
async def test_clear_cache() -> None:
    async def builder() -> str:
        return "x"

    await register_section("k1", builder)
    assert section_cache_size() == 1
    clear_section_cache()
    assert section_cache_size() == 0
