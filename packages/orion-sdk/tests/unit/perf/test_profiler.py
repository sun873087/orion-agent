"""Profiler — sync + async ctx managers + render。"""

from __future__ import annotations

import time

import anyio
import pytest

from orion_sdk.perf.profiler import (
    profile_async,
    profile_sync,
    render_profile,
)


def test_profile_sync() -> None:
    with profile_sync() as prof:
        # 一些可被 profile 抓到的工作
        sum_ = 0
        for i in range(100_000):
            sum_ += i
    text = render_profile(prof)
    assert isinstance(text, str)
    assert len(text) > 0


@pytest.mark.asyncio
async def test_profile_async() -> None:
    async with profile_async() as prof:
        await anyio.sleep(0.05)
        # CPU work
        sum_ = 0
        for i in range(10_000):
            sum_ += i
    text = render_profile(prof)
    assert isinstance(text, str)
    assert len(text) > 0


def test_render_with_color_returns_str() -> None:
    with profile_sync() as prof:
        time.sleep(0.01)
    text = render_profile(prof, color=True)
    assert isinstance(text, str)
