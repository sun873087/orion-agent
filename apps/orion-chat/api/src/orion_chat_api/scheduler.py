"""背景 scheduler — cron 到點時以 schedule 擁有者身分自動跑一輪(act 模式)。

單 instance 版:60s tick + 「fire 前先把 next_run_at 推到下一次」當去重(即使這輪
turn 跑很久,下個 tick 也不會重複挑到)+ in-process `_running` 再保險。多 worker
leader election / DB advisory lock 留 enterprise(見 routes/schedules.py 註解)。

fire 規則(對齊 cowork scheduler._execute_schedule):
- trigger=prompt → payload 當 prompt;trigger=skill → 提示載指定 skill。
- target_session_id 有值(Loop)→ 送回既有 session;否則開新 session。
- 一律 act 模式(autonomous,不問 user)。catch-up 策略:錯過的不補跑,只推下次。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any
from uuid import UUID, uuid4

from croniter import croniter
from sqlalchemy import select

from orion_chat_api.user_context import build_user_system_prefix
from orion_sdk.core.conversation import Conversation, pick_max_tokens_per_turn
from orion_sdk.core.state import AgentContext
from orion_sdk.permissions.decisions import PermissionDecision, PermissionResult
from orion_sdk.storage.db.engine import db_session
from orion_sdk.storage.db.models import Schedule as ScheduleRow
from orion_sdk.storage.paths import session_paths
from orion_sdk.tools.builtin_set import build_default_tool_set

logger = logging.getLogger(__name__)

TICK_SECONDS = 60.0


async def _allow_all(_tool: Any, _tool_input: Any, _ctx: Any) -> PermissionResult:
    """autonomous fire = 全放行(沒有 user 在線可回答 permission)。"""
    return PermissionResult(decision=PermissionDecision.ALLOW)


def _next_run(cron_expr: str, base: float | None = None) -> float:
    return float(croniter(cron_expr, base or time.time()).get_next(float))


def _prompt_for(row: ScheduleRow) -> str:
    if row.trigger_type == "skill":
        return (
            f"Load and run the '{row.payload}' skill via the Skill tool, "
            "then carry out what it describes."
        )
    return row.payload


async def run_schedule_now(app: Any, sched_id: str, *, advance: bool) -> str | None:
    """fire 一個 schedule。回跑的 session_id;schedule / target session 不存在回 None。

    advance=True 會先把 next_run_at 推到下次(背景 tick 用,防重複);run_now 端點
    傳 False(手動觸發不動排程時刻)。
    """
    engine = app.state.db_engine
    sm = app.state.session_manager
    if engine is None or sm is None:
        return None

    async with db_session(engine) as db:
        row = (
            await db.execute(select(ScheduleRow).where(ScheduleRow.id == sched_id))
        ).scalar_one_or_none()
    if row is None:
        return None

    if advance and row.cron_expr:
        with contextlib.suppress(ValueError, KeyError):
            nxt = _next_run(row.cron_expr)
            async with db_session(engine) as db:
                r2 = (
                    await db.execute(
                        select(ScheduleRow).where(ScheduleRow.id == sched_id),
                    )
                ).scalar_one_or_none()
                if r2 is not None:
                    r2.next_run_at = nxt
                    await db.commit()

    user_id = row.user_id
    prompt = _prompt_for(row)

    # Loop(送回既有 session)vs 新開 session
    if row.target_session_id:
        sid = UUID(row.target_session_id)
        conv = await sm.get(user_id, sid)
        if conv is None:
            return None
    else:
        provider = app.state.llm_provider
        conv = Conversation(
            provider=provider,
            user_id=user_id,
            tools=build_default_tool_set(),
            max_tokens_per_turn=pick_max_tokens_per_turn(
                provider.name, provider.model,
            ),
            system_prompt=build_user_system_prefix(user_id),
            include_workspace_context=False,
        )
        sid = await sm.create(
            user_id=user_id, session_id=conv.session_id, conversation=conv,
        )

    conv.can_use_tool = _allow_all  # autonomous → act
    sp = session_paths(sid)
    sp.ensure_dirs()
    ctx = AgentContext(session_id=sid, user_id=user_id, cwd=sp.workspace_dir)
    async for _ev in conv.send(prompt, ctx=ctx):
        pass

    with contextlib.suppress(Exception):
        await sm.sync_stats(user_id, sid)
    async with db_session(engine) as db:
        r3 = (
            await db.execute(select(ScheduleRow).where(ScheduleRow.id == sched_id))
        ).scalar_one_or_none()
        if r3 is not None:
            r3.last_run_at = time.time()
            await db.commit()
    return str(sid)


class SchedulerEngine:
    """背景 tick loop。app.state.scheduler 持有;lifespan start/stop。"""

    def __init__(self, app: Any) -> None:
        self.app = app
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._running: set[str] = set()

    @property
    def _engine(self) -> Any:
        return self.app.state.db_engine

    async def start(self) -> None:
        if self._task is not None:
            return
        await self._catch_up()
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="orion-scheduler")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._task, timeout=5.0)
            self._task = None

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception:  # noqa: BLE001 — tick 失敗不該殺掉 loop
                logger.exception("scheduler tick failed")
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=TICK_SECONDS)

    async def _catch_up(self) -> None:
        """啟動時把過時的 next_run_at 推到未來(錯過的不補跑)。"""
        now = time.time()
        async with db_session(self._engine) as db:
            rows = (
                await db.execute(
                    select(ScheduleRow).where(ScheduleRow.enabled.is_(True)),
                )
            ).scalars().all()
            for r in rows:
                if r.next_run_at is not None and r.next_run_at >= now:
                    continue
                with contextlib.suppress(ValueError, KeyError):
                    r.next_run_at = _next_run(r.cron_expr, now)
            await db.commit()

    async def _tick(self) -> None:
        now = time.time()
        async with db_session(self._engine) as db:
            due = (
                await db.execute(
                    select(ScheduleRow).where(
                        ScheduleRow.enabled.is_(True),
                        ScheduleRow.next_run_at.is_not(None),
                        ScheduleRow.next_run_at <= now,
                    ),
                )
            ).scalars().all()
        for r in due:
            if r.id in self._running:
                continue
            self._running.add(r.id)
            asyncio.create_task(self._fire(r.id), name=f"sched-{r.id[:8]}")

    async def _fire(self, sched_id: str) -> None:
        try:
            await run_schedule_now(self.app, sched_id, advance=True)
        except Exception:  # noqa: BLE001
            logger.exception("schedule fire failed: %s", sched_id)
        finally:
            self._running.discard(sched_id)
