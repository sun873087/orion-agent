"""Admin action audit — admin_routes + admin_ui 內每個寫操作都呼一次 record()。

不阻塞主流 — fire-and-forget。失敗 swallow(audit 掛掉不該擋 user CRUD)。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from orion_model_proxy.models import AuditLog

_log = logging.getLogger(__name__)


async def record(
    s: AsyncSession,
    *,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """同 session 內 add + commit。失敗只 log,不 raise(audit ≠ business logic)。"""
    try:
        row = AuditLog(
            ts=int(time.time()),
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=json.dumps(detail, ensure_ascii=False) if detail is not None else None,
        )
        s.add(row)
        await s.commit()
    except Exception as e:  # noqa: BLE001
        _log.warning("audit record failed for %s: %s", action, e)


def record_async(
    s: AsyncSession,
    *,
    action: str,
    **kwargs: Any,
) -> asyncio.Task[None]:
    """Fire-and-forget 版本 — caller 不必 await。"""
    return asyncio.create_task(record(s, action=action, **kwargs))


__all__ = ["record", "record_async"]
