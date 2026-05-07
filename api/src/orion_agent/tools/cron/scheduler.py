"""CronScheduler — APScheduler AsyncIOScheduler wrapper。

Phase 10 範圍 single-instance,in-memory job store。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


@dataclass
class CronJob:
    """已排程的 cron job 摘要。"""

    id: str
    name: str
    """human-readable 名稱。"""
    cron_expr: str
    """5-field cron(分 時 日 月 週)。"""
    command: str
    """要跑的 shell command。"""
    enabled: bool = True

    next_run_time: datetime | None = None

    def to_summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "cron_expr": self.cron_expr,
            "command": self.command,
            "enabled": self.enabled,
            "next_run_time": self.next_run_time.isoformat() if self.next_run_time else None,
        }


def _parse_cron(expr: str) -> CronTrigger:
    """5-field cron → APScheduler CronTrigger。"""
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(f"cron expr must have 5 fields, got {len(parts)}: {expr!r}")
    minute, hour, day, month, day_of_week = parts
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
    )


class CronScheduler:
    """thin wrapper 圍 AsyncIOScheduler + in-memory 名稱→id map。"""

    def __init__(self) -> None:
        self._sched = AsyncIOScheduler()
        self._jobs: dict[str, CronJob] = {}
        self._started = False

    def start(self) -> None:
        if not self._started:
            self._sched.start()
            self._started = True

    def shutdown(self) -> None:
        if self._started:
            with contextlib.suppress(Exception):
                self._sched.shutdown(wait=False)
            self._started = False

    def reset(self) -> None:
        self.shutdown()
        self._jobs.clear()

    def add(
        self,
        *,
        name: str,
        cron_expr: str,
        command: str,
    ) -> CronJob:
        if not self._started:
            self.start()
        trigger = _parse_cron(cron_expr)
        job_id = uuid4().hex[:12]

        async def _run() -> None:
            try:
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                await proc.wait()
            except Exception as e:  # noqa: BLE001
                logger.warning("cron job %s failed: %s", name, e)

        ap_job = self._sched.add_job(_run, trigger, id=job_id, name=name, replace_existing=True)
        cj = CronJob(
            id=job_id,
            name=name,
            cron_expr=cron_expr,
            command=command,
            next_run_time=ap_job.next_run_time,
        )
        self._jobs[job_id] = cj
        return cj

    def list(self) -> list[CronJob]:
        # refresh next_run_time
        for jid, cj in self._jobs.items():
            ap = self._sched.get_job(jid) if self._started else None
            cj.next_run_time = ap.next_run_time if ap is not None else None
        return list(self._jobs.values())

    def delete(self, job_id: str) -> bool:
        cj = self._jobs.get(job_id)
        if cj is None:
            return False
        with contextlib.suppress(Exception):
            self._sched.remove_job(job_id)
        del self._jobs[job_id]
        return True


# ─── global singleton ────────────────────────────────────────────────────


_scheduler: CronScheduler | None = None


def get_scheduler() -> CronScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = CronScheduler()
    return _scheduler


def reset_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.reset()
    _scheduler = None
