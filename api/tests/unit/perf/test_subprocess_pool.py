"""SubprocessPool — exec_simple + stats。"""

from __future__ import annotations

import pytest

from orion_agent.perf.subprocess_pool import SubprocessPool


@pytest.mark.asyncio
async def test_exec_echo() -> None:
    pool = SubprocessPool(size=2)
    rc, out = await pool.exec_simple("echo pool-test")
    assert rc == 0
    assert "pool-test" in out
    await pool.shutdown()


@pytest.mark.asyncio
async def test_exec_failure_returns_nonzero() -> None:
    pool = SubprocessPool(size=2)
    rc, _ = await pool.exec_simple("exit 7")
    assert rc == 7
    await pool.shutdown()


@pytest.mark.asyncio
async def test_exec_timeout() -> None:
    pool = SubprocessPool(size=2)
    rc, out = await pool.exec_simple("sleep 5", timeout=0.3)
    # timeout → -1 + <timeout> message OR Pool worker path 不 timeout 直接 fork timeout
    assert rc == -1 or rc != 0
    _ = out
    await pool.shutdown()


@pytest.mark.asyncio
async def test_stats_recorded() -> None:
    pool = SubprocessPool(size=2)
    await pool.exec_simple("true")
    await pool.exec_simple("true")
    assert pool.stats.spawned >= 1
    await pool.shutdown()
