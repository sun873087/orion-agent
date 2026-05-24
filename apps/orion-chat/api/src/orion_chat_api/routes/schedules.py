"""/schedules — per-user cron 排程 / Loop CRUD。

cron 用 croniter 驗證 + 算 next_run_at。**背景 firing daemon**(多 worker leader
election + 以 schedule.user_id 身分跑 turn)是路線圖的最大風險項,留待獨立 worker
實作;這層先把排程 CRUD + cron 引擎做好(run_now 立即算下次時間)。
"""

from __future__ import annotations

import time
from typing import Annotated, Literal
from uuid import UUID, uuid4

from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.requests import Request

from orion_chat_api.deps import current_user
from orion_sdk.storage.db.engine import db_session
from orion_sdk.storage.db.models import Schedule as ScheduleRow

router = APIRouter()


def _engine(request: Request) -> AsyncEngine:
    engine = getattr(request.app.state, "db_engine", None)
    if engine is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "schedules require ORION_DB_URL",
        )
    return engine


def _next_run(cron_expr: str, base: float | None = None) -> float:
    """算下次執行的 epoch 秒。cron 無效 raise ValueError(croniter)。"""
    return float(croniter(cron_expr, base or time.time()).get_next(float))


class ScheduleBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    cron_expr: str = Field(min_length=1, max_length=120)
    trigger_type: Literal["prompt", "skill"] = "prompt"
    payload: str = ""
    enabled: bool = True
    target_session_id: str | None = None


class ScheduleSummary(BaseModel):
    id: str
    name: str
    cron_expr: str
    trigger_type: str
    payload: str
    enabled: bool
    target_session_id: str | None = None
    next_run_at: float | None = None


def _to_summary(r: ScheduleRow) -> ScheduleSummary:
    return ScheduleSummary(
        id=r.id,
        name=r.name,
        cron_expr=r.cron_expr,
        trigger_type=r.trigger_type,
        payload=r.payload,
        enabled=bool(r.enabled),
        target_session_id=r.target_session_id,
        next_run_at=r.next_run_at,
    )


async def _owned(engine: AsyncEngine, sched_id: str, user_id: str) -> ScheduleRow:
    async with db_session(engine) as db:
        row = (
            await db.execute(
                select(ScheduleRow).where(
                    ScheduleRow.id == sched_id, ScheduleRow.user_id == user_id,
                ),
            )
        ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "schedule not found")
    return row


@router.get("/schedules", response_model=list[ScheduleSummary])
async def list_schedules(
    request: Request,
    user_id: Annotated[str, Depends(current_user)],
) -> list[ScheduleSummary]:
    engine = _engine(request)
    async with db_session(engine) as db:
        rows = (
            await db.execute(
                select(ScheduleRow)
                .where(ScheduleRow.user_id == user_id)
                .order_by(ScheduleRow.created_at.desc()),
            )
        ).scalars().all()
    return [_to_summary(r) for r in rows]


@router.post(
    "/schedules", response_model=ScheduleSummary, status_code=status.HTTP_201_CREATED,
)
async def create_schedule(
    body: ScheduleBody,
    request: Request,
    user_id: Annotated[str, Depends(current_user)],
) -> ScheduleSummary:
    engine = _engine(request)
    try:
        nxt = _next_run(body.cron_expr)
    except (ValueError, KeyError) as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"invalid cron: {e}",
        ) from e
    row = ScheduleRow(
        id=str(uuid4()),
        user_id=user_id,
        name=body.name,
        cron_expr=body.cron_expr,
        trigger_type=body.trigger_type,
        payload=body.payload,
        enabled=body.enabled,
        target_session_id=body.target_session_id,
        next_run_at=nxt,
    )
    async with db_session(engine) as db:
        db.add(row)
        await db.commit()
    return _to_summary(row)


@router.put("/schedules/{sched_id}", response_model=ScheduleSummary)
async def update_schedule(
    sched_id: str,
    body: ScheduleBody,
    request: Request,
    user_id: Annotated[str, Depends(current_user)],
) -> ScheduleSummary:
    engine = _engine(request)
    await _owned(engine, sched_id, user_id)
    try:
        nxt = _next_run(body.cron_expr)
    except (ValueError, KeyError) as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"invalid cron: {e}",
        ) from e
    async with db_session(engine) as db:
        row = (
            await db.execute(select(ScheduleRow).where(ScheduleRow.id == sched_id))
        ).scalar_one()
        row.name = body.name
        row.cron_expr = body.cron_expr
        row.trigger_type = body.trigger_type
        row.payload = body.payload
        row.enabled = body.enabled
        row.target_session_id = body.target_session_id
        row.next_run_at = nxt
        await db.commit()
        return _to_summary(row)


@router.delete("/schedules/{sched_id}")
async def delete_schedule(
    sched_id: str,
    request: Request,
    user_id: Annotated[str, Depends(current_user)],
) -> dict[str, bool]:
    engine = _engine(request)
    await _owned(engine, sched_id, user_id)
    async with db_session(engine) as db:
        await db.execute(delete(ScheduleRow).where(ScheduleRow.id == sched_id))
        await db.commit()
    return {"deleted": True}
