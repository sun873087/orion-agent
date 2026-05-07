"""Profiler — Phase 10。pyinstrument 包裝。

兩個 ctx manager:
- `profile_sync()`:同步程式碼
- `profile_async()`:async 程式碼(pyinstrument 內部會切到 async-aware mode)

`render_profile(profiler)` 回 console-friendly text 報告。

用法:
```python
from orion_agent.perf.profiler import profile_async, render_profile

async with profile_async() as prof:
    await heavy_async_work()
print(render_profile(prof))
```
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager

from pyinstrument import Profiler


@contextmanager
def profile_sync() -> Iterator[Profiler]:
    """同步 ctx manager。"""
    p = Profiler()
    p.start()
    try:
        yield p
    finally:
        p.stop()


@asynccontextmanager
async def profile_async() -> AsyncIterator[Profiler]:
    """async-aware ctx manager。pyinstrument 4.6+ 對 asyncio 友善。"""
    p = Profiler(async_mode="enabled")
    p.start()
    try:
        yield p
    finally:
        p.stop()


def render_profile(profiler: Profiler, *, color: bool = False) -> str:
    """產 console-friendly text 報告。`color=True` 加 ANSI(terminal 友善)。"""
    return profiler.output_text(unicode=True, color=color)
