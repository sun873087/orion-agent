"""webhook 系統。

Admin 可建 webhook(POST URL + event filter),proxy 在特定 event 發生時
fire-and-forget POST 一個 JSON payload 給 user 設的 URL。

Events:
    budget.warning_80 user 累積 cost >= budget × 80% 第一次觸發
    budget.exceeded >= 100%
    key.revoked admin revoke key 後 emit
    user.created admin create user 後 emit

Payload 結構:
    {
      "event": "...",
      "ts": 1700000000,
      "user_id": "...",
      "user_email": "...",
      "data": { ... event-specific ... }
    }

Webhook URL 是 Slack / Discord / 自家 endpoint — JSON-friendly 都收。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orion_model_proxy.models import User, Webhook

_log = logging.getLogger(__name__)


# 已 fire 的 budget event 避免重複(per-process,user_id → set of events fired)
_fired_budget_events: dict[str, set[str]] = {}
_fired_lock = asyncio.Lock()


async def _list_webhooks(s: AsyncSession, *, event: str, user_id: str | None) -> list[Webhook]:
    """這個 event 該打哪些 webhook:user 專屬 + 全域(user_id IS NULL)。"""
    stmt = select(Webhook).where(Webhook.event == event).where(Webhook.enabled.is_(True))
    rows = (await s.execute(stmt)).scalars().all()
    return [w for w in rows if w.user_id is None or w.user_id == user_id]


async def _post_one(url: str, payload: dict[str, Any]) -> None:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, json=payload)
    except Exception as e: # noqa: BLE001
        _log.warning("webhook POST %s failed: %s", url, e)


async def emit(
    s: AsyncSession,
    *,
    event: str,
    user_id: str,
    data: dict[str, Any] | None = None,
) -> None:
    """Fire 對應 webhook(背景,不阻塞 caller)。"""
    user = await s.get(User, user_id)
    user_email = user.email if user else "unknown@unknown"
    hooks = await _list_webhooks(s, event=event, user_id=user_id)
    if not hooks:
        return
    payload = {
        "event": event,
        "ts": int(time.time()),
        "user_id": user_id,
        "user_email": user_email,
        "data": data or {},
    }
    for h in hooks:
        asyncio.create_task(_post_one(h.url, payload))


async def maybe_emit_budget_event(
    s: AsyncSession,
    *,
    user_id: str,
    running_cost: float,
    budget_cap: float,
) -> None:
    """budget 達 80% / 100% 時 emit(per-user 每 event 只 fire 一次,until reset)。"""
    pct = (running_cost / budget_cap) if budget_cap > 0 else 0.0
    async with _fired_lock:
        fired = _fired_budget_events.setdefault(user_id, set())
        events_to_fire: list[str] = []
        if pct >= 1.0 and "budget.exceeded" not in fired:
            fired.add("budget.exceeded")
            events_to_fire.append("budget.exceeded")
        if pct >= 0.8 and "budget.warning_80" not in fired:
            fired.add("budget.warning_80")
            events_to_fire.append("budget.warning_80")
    for evt in events_to_fire:
        await emit(s, event=evt, user_id=user_id,
                   data={"running_cost": running_cost, "budget_cap": budget_cap, "pct": pct})


async def reset_for_tests() -> None:
    async with _fired_lock:
        _fired_budget_events.clear()


__all__ = ["emit", "maybe_emit_budget_event", "reset_for_tests"]
