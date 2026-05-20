"""Phase X.2 — usage_log insert(fire-and-forget,不阻塞 request)+ running cost
cache。

Cache 給 Phase X.3 budget enforcement 用:per-user 累積 USD,TTL 60s,寫入時
incr,讀時 fallback DB rollup。
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time

from orion_model_proxy.usage_parser import UsageEvent

_log = logging.getLogger(__name__)

# user_id → (running_cost_usd, last_refresh_ts)
_running_cost: dict[str, tuple[float, float]] = {}
_running_cost_lock = asyncio.Lock()
_TTL_SECONDS = 60.0


async def get_running_cost(user_id: str) -> float:
    """Cache hit / DB recompute(月初到現在)。"""
    now = time.time()
    async with _running_cost_lock:
        cached = _running_cost.get(user_id)
        if cached is not None and (now - cached[1]) < _TTL_SECONDS:
            return cached[0]

    # Cache miss → DB rollup
    from datetime import datetime, timezone
    from sqlalchemy import func, select

    from orion_model_proxy.db import get_session_factory
    from orion_model_proxy.models import UsageLog

    first_of_month = datetime.now(timezone.utc).astimezone()
    first_of_month = first_of_month.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    from_ts = int(first_of_month.timestamp())

    factory = get_session_factory()
    async with factory() as s:
        stmt = (
            select(func.coalesce(func.sum(UsageLog.cost_usd), 0.0))
            .where(UsageLog.user_id == user_id)
            .where(UsageLog.ts >= from_ts)
        )
        total = float((await s.execute(stmt)).scalar() or 0.0)

    async with _running_cost_lock:
        _running_cost[user_id] = (total, now)
    return total


async def incr_running_cost(user_id: str, delta_usd: float) -> None:
    """Post-request 加進 cache。"""
    async with _running_cost_lock:
        cached = _running_cost.get(user_id)
        base = cached[0] if cached is not None else 0.0
        _running_cost[user_id] = (base + delta_usd, time.time())


async def reset_running_cost_for_tests() -> None:
    async with _running_cost_lock:
        _running_cost.clear()


async def log_usage(
    *,
    user_id: str,
    api_key_id: str,
    event: UsageEvent,
    client_id: str | None = None,
    request_id: str | None = None,
) -> None:
    """Insert usage_log row + incr running cost cache。失敗 swallow,best-effort。"""
    try:
        from orion_model_proxy.db import get_session_factory
        from orion_model_proxy.models import UsageLog

        factory = get_session_factory()
        async with factory() as s:
            row = UsageLog(
                user_id=user_id,
                api_key_id=api_key_id,
                provider=event.provider,
                model=event.model,
                endpoint=event.endpoint,
                input_tokens=event.input_tokens,
                output_tokens=event.output_tokens,
                cache_read_tokens=event.cache_read_tokens,
                cache_creation_tokens=event.cache_creation_tokens,
                cost_usd=event.cost_usd,
                ts=int(time.time()),
                client_id=client_id,
                request_id=request_id,
            )
            s.add(row)
            await s.commit()

            # Phase 33-D — budget threshold webhook 通知。讀回 user.budget_usd
            # 跟最新 running cost,> 80% / 100% 時 emit(per-event per-user 只
            # fire 一次,reset 在 set_budget 時走 cache invalidate)。
            from orion_model_proxy.models import User
            from orion_model_proxy.webhook import maybe_emit_budget_event

            user = await s.get(User, user_id)
            if user is not None and user.budget_usd is not None:
                running = (await get_running_cost(user_id)) + event.cost_usd
                await maybe_emit_budget_event(
                    s, user_id=user_id,
                    running_cost=running, budget_cap=user.budget_usd,
                )
        await incr_running_cost(user_id, event.cost_usd)
    except Exception as e:  # noqa: BLE001 — fire-and-forget
        _log.warning("usage_log insert failed for %s: %s", user_id, e)


__all__ = [
    "get_running_cost",
    "incr_running_cost",
    "log_usage",
    "reset_running_cost_for_tests",
]
