"""usage_log 月歸檔。

>cutoff_days 前的 row 壓進 usage_monthly(by year_month × user × provider ×
model 聚合)然後刪 raw row。SQLite 跑久了 row 數會炸,這 keeps it bounded。

Idempotent:呼多次只會把舊資料再聚合一次(年月相同 row 會被 ON CONFLICT
upsert 合併 — 但我們用 manual upsert,跨 SQLite/PG 通用)。
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from orion_model_proxy.models import UsageLog, UsageMonthlyRollup

_log = logging.getLogger(__name__)


@dataclass
class ArchiveStats:
    rows_archived: int
    rollup_rows_upserted: int
    cutoff_ts: int


async def archive_usage_log(
    s: AsyncSession, *, cutoff_days: int = 90
) -> ArchiveStats:
    """把 cutoff_days 之前的 usage_log row 移進 usage_monthly。

    跨 backend 寫法:select → aggregate in Python → upsert via manual
    `SELECT then INSERT/UPDATE`(不用 SQLite/PG-specific ON CONFLICT)。
    """
    cutoff_ts = int((dt.datetime.now(dt.timezone.utc)
                     - dt.timedelta(days=cutoff_days)).timestamp())

    # 1. 拉舊 row
    old_rows = (
        await s.execute(
            select(UsageLog).where(UsageLog.ts < cutoff_ts)
        )
    ).scalars().all()
    if not old_rows:
        return ArchiveStats(rows_archived=0, rollup_rows_upserted=0, cutoff_ts=cutoff_ts)

    # 2. Bucket
    buckets: dict[tuple[str, str, str, str], dict[str, float | int]] = defaultdict(
        lambda: {"input": 0, "output": 0, "cost": 0.0, "count": 0}
    )
    for r in old_rows:
        ym = dt.datetime.fromtimestamp(r.ts, dt.timezone.utc).strftime("%Y-%m")
        key = (r.user_id, ym, r.provider, r.model)
        b = buckets[key]
        b["input"] = (b["input"] or 0) + (r.input_tokens or 0)
        b["output"] = (b["output"] or 0) + (r.output_tokens or 0)
        b["cost"] = (b["cost"] or 0.0) + r.cost_usd
        b["count"] = (b["count"] or 0) + 1

    # 3. Upsert into usage_monthly
    upsert_count = 0
    for (user_id, ym, provider, model), b in buckets.items():
        existing = (
            await s.execute(
                select(UsageMonthlyRollup)
                .where(UsageMonthlyRollup.user_id == user_id)
                .where(UsageMonthlyRollup.year_month == ym)
                .where(UsageMonthlyRollup.provider == provider)
                .where(UsageMonthlyRollup.model == model)
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.total_input_tokens += int(b["input"])
            existing.total_output_tokens += int(b["output"])
            existing.total_cost_usd += float(b["cost"])
            existing.request_count += int(b["count"])
        else:
            s.add(
                UsageMonthlyRollup(
                    user_id=user_id,
                    year_month=ym,
                    provider=provider,
                    model=model,
                    total_input_tokens=int(b["input"]),
                    total_output_tokens=int(b["output"]),
                    total_cost_usd=float(b["cost"]),
                    request_count=int(b["count"]),
                )
            )
        upsert_count += 1

    # 4. Delete archived raw rows
    await s.execute(delete(UsageLog).where(UsageLog.ts < cutoff_ts))
    await s.commit()
    _log.info(
        "archived %d usage_log rows → %d monthly rollup rows (cutoff=%s)",
        len(old_rows), upsert_count,
        dt.datetime.fromtimestamp(cutoff_ts, dt.timezone.utc).isoformat(),
    )
    return ArchiveStats(
        rows_archived=len(old_rows),
        rollup_rows_upserted=upsert_count,
        cutoff_ts=cutoff_ts,
    )


__all__ = ["ArchiveStats", "archive_usage_log"]
