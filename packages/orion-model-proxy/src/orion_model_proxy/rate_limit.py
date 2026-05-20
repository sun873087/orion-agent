"""Phase 33-B — per-user token bucket rate limit。

Single-process in-memory bucket(production 多 instance 改 Redis-backed)。
User 上 rate_limit_rpm 在 users 表 add 一個 column;沒設 → 不限。

Algorithm:每 user 一個 bucket = (tokens float, last_refill_ts float)。
每次 request:
    elapsed = now - last_refill_ts
    tokens += elapsed * (rpm / 60.0)
    tokens = min(tokens, rpm)  # cap at burst size = rpm
    if tokens >= 1: tokens -= 1; return ok
    else: 429
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    last_refill_ts: float


_buckets: dict[str, _Bucket] = {}
_lock = asyncio.Lock()


async def check_and_consume(user_id: str, rpm: int) -> bool:
    """Return True 表示放行,False 表示已超 rate limit。

    rpm = 0 視為不限。
    """
    if rpm <= 0:
        return True
    now = time.monotonic()
    async with _lock:
        b = _buckets.get(user_id)
        if b is None:
            b = _Bucket(tokens=float(rpm), last_refill_ts=now)
            _buckets[user_id] = b
        # Refill
        elapsed = now - b.last_refill_ts
        b.tokens = min(float(rpm), b.tokens + elapsed * (rpm / 60.0))
        b.last_refill_ts = now
        if b.tokens >= 1.0:
            b.tokens -= 1.0
            return True
        return False


async def reset_for_tests() -> None:
    async with _lock:
        _buckets.clear()


__all__ = ["check_and_consume", "reset_for_tests"]
