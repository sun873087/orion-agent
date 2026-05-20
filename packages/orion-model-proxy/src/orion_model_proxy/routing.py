"""Phase 33-E — routing alias 解析。

Client 送 model="auto-fast" → proxy 查 routing_aliases:
    1. user-specific(user_id=<X> + alias="auto-fast")
    2. global(user_id=NULL + alias="auto-fast")
    3. 沒對應 → 原樣 forward

Reverse proxy 在 forward 前改 request body 的 `model` 欄(JSON-only),
透傳給 upstream。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orion_model_proxy.models import RoutingAlias

_log = logging.getLogger(__name__)


async def resolve_alias(
    s: AsyncSession, *, alias: str, user_id: str
) -> tuple[str, str] | None:
    """Return (target_provider, target_model) or None if no match。"""
    # User-specific 先
    stmt = (
        select(RoutingAlias)
        .where(RoutingAlias.alias == alias)
        .where(RoutingAlias.user_id == user_id)
        .limit(1)
    )
    row = (await s.execute(stmt)).scalar_one_or_none()
    if row is None:
        # Global fallback
        stmt = (
            select(RoutingAlias)
            .where(RoutingAlias.alias == alias)
            .where(RoutingAlias.user_id.is_(None))
            .limit(1)
        )
        row = (await s.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None
    return (row.target_provider, row.target_model)


def rewrite_model_in_body(body: bytes, new_model: str) -> bytes:
    """JSON body 的 `model` 欄改成 new_model。非 JSON 原樣回。"""
    if not body:
        return body
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return body
    if isinstance(data, dict) and "model" in data:
        data["model"] = new_model
        return json.dumps(data, ensure_ascii=False).encode("utf-8")
    return body


__all__ = ["resolve_alias", "rewrite_model_in_body"]
