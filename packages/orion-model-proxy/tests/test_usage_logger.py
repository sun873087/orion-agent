"""usage_logger DB insert + running cost cache。"""

from __future__ import annotations

import time

import pytest

from orion_model_proxy.usage_logger import (
    get_running_cost,
    incr_running_cost,
    log_usage,
    reset_running_cost_for_tests,
)
from orion_model_proxy.usage_parser import UsageEvent


@pytest.mark.asyncio
async def test_log_usage_inserts_row(proxy_db) -> None:
    from sqlalchemy import select
    from orion_model_proxy.db import get_session_factory
    from orion_model_proxy.models import UsageLog

    await reset_running_cost_for_tests()
    ev = UsageEvent(
        provider="openai", model="gpt-5-mini",
        endpoint="/openai/v1/chat/completions",
        input_tokens=100, output_tokens=50,
        cache_read_tokens=0, cache_creation_tokens=None,
        cost_usd=0.000075,
    )
    await log_usage(
        user_id="u1", api_key_id="k1", event=ev,
        client_id="orion-cli", request_id="req-1",
    )

    factory = get_session_factory()
    async with factory() as s:
        rows = (await s.execute(select(UsageLog))).scalars().all()
    assert len(rows) == 1
    r = rows[0]
    assert r.user_id == "u1"
    assert r.model == "gpt-5-mini"
    assert r.cost_usd == pytest.approx(0.000075)
    assert r.client_id == "orion-cli"


@pytest.mark.asyncio
async def test_running_cost_db_rollup_and_cache(proxy_db) -> None:
    from sqlalchemy import select
    from orion_model_proxy.db import get_session_factory
    from orion_model_proxy.models import UsageLog

    await reset_running_cost_for_tests()
    ev1 = UsageEvent(
        provider="openai", model="gpt-5-mini", endpoint="/openai/v1/chat/completions",
        input_tokens=100, output_tokens=50, cache_read_tokens=0,
        cache_creation_tokens=None, cost_usd=0.001,
    )
    ev2 = UsageEvent(
        provider="anthropic", model="claude-haiku-4-5", endpoint="/anthropic/v1/messages",
        input_tokens=200, output_tokens=100, cache_read_tokens=0,
        cache_creation_tokens=None, cost_usd=0.002,
    )
    await log_usage(user_id="u-running", api_key_id="k", event=ev1)
    await log_usage(user_id="u-running", api_key_id="k", event=ev2)

    # log_usage 寫完會 incr cache;讀 cache hit
    cost = await get_running_cost("u-running")
    assert cost == pytest.approx(0.003)

    # 清 cache,DB rollup 也應該對
    await reset_running_cost_for_tests()
    cost = await get_running_cost("u-running")
    assert cost == pytest.approx(0.003)


@pytest.mark.asyncio
async def test_incr_running_cost_isolation(proxy_db) -> None:
    """不同 user 各自累加,不會 cross-contaminate。"""
    await reset_running_cost_for_tests()
    await incr_running_cost("user-a", 1.5)
    await incr_running_cost("user-b", 0.5)
    await incr_running_cost("user-a", 0.25)

    # 因為沒走 log_usage,DB 沒料,但 cache 內有
    a = await get_running_cost("user-a")
    b = await get_running_cost("user-b")
    assert a == pytest.approx(1.75)
    assert b == pytest.approx(0.5)
