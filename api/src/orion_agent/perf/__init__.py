"""Performance utilities — Phase 10。

- `subprocess_pool.py`:async-friendly subprocess pool(避免每次 fork)
- `profiler.py`:pyinstrument 包裝(profile_async ctx manager)
"""

from __future__ import annotations

from orion_agent.perf.profiler import profile_async, profile_sync, render_profile
from orion_agent.perf.subprocess_pool import (
    PooledProcess,
    SubprocessPool,
    get_pool,
    reset_pool,
)

__all__ = [
    "PooledProcess",
    "SubprocessPool",
    "get_pool",
    "profile_async",
    "profile_sync",
    "render_profile",
    "reset_pool",
]
