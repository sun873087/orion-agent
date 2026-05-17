"""背景排程引擎 — 跑在 sidecar asyncio loop 內。

設計重點:
- Tick 60s,從 DB 撈 enabled + due 的 schedules
- 同筆 schedule 上次還在跑 → 跳過下一次 tick(_running_ids 擋)
- 觸發 = 內部呼 conversation.create + conversation.send 開新 session 跑 LLM loop
- 失敗也要 record_schedule_run + 算 next_run_at(否則 stuck 在過去時點)
- App 啟動時 catch-up:錯過的不補跑,只把 next_run_at 推到下個未來 tick
- App 關閉 = 排程不跑(本期不做 OS-level daemon)
"""

from __future__ import annotations

import asyncio
import sys
import time
from typing import TYPE_CHECKING, Any

from croniter import croniter

from orion_cowork_sidecar import storage

if TYPE_CHECKING:
    from orion_cowork_sidecar.handlers import Handlers


TICK_SECONDS = 60.0


def compute_next_run_at(cron_expr: str, *, base: float | None = None) -> float:
    """算下次該跑的 epoch seconds。caller 須先 is_valid_cron 過。"""
    base_ts = base if base is not None else time.time()
    it = croniter(cron_expr, base_ts)
    return float(it.get_next())


def is_valid_cron(expr: str) -> bool:
    try:
        croniter(expr)
        return True
    except Exception:  # noqa: BLE001
        return False


class SchedulerEngine:
    """asyncio tick 排程器。生命週期跟 sidecar 同。"""

    def __init__(self, handlers: "Handlers") -> None:
        self._handlers = handlers
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()
        self._running_ids: set[str] = set()

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.is_running():
            return
        try:
            await self._catch_up_next_runs()
        except Exception as e:  # noqa: BLE001
            print(f"[scheduler] catch-up failed: {e}", file=sys.stderr, flush=True)
        self._stopping.clear()
        self._task = asyncio.create_task(self._loop(), name="cowork-scheduler")

    async def stop(self) -> None:
        self._stopping.set()
        t = self._task
        self._task = None
        if t is None:
            return
        try:
            await asyncio.wait_for(t, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            t.cancel()

    async def run_now(self, schedule_id: str) -> str | None:
        """手動立刻觸發一筆排程(UI「立即執行」按鈕)— 回新 session_id 或 None。

        不更新 next_run_at(它仍按 cron 走);也不過 _running_ids 防重(user 顯式
        操作優先)。
        """
        engine = await self._handlers.ensure_engine()
        sch = await storage.get_schedule(engine, schedule_id)
        if sch is None:
            return None
        return await self._run_schedule_now(sch, mark_run=True)

    async def _catch_up_next_runs(self) -> None:
        """啟動時把任何 next_run_at 落後 / NULL 的 enabled schedule 推到下個未來
        tick — 過去錯過的不補跑。"""
        engine = await self._handlers.ensure_engine()
        now = time.time()
        items = await storage.list_schedules(engine, enabled_only=True)
        for sch in items:
            if sch.next_run_at is not None and sch.next_run_at >= now:
                continue
            if not is_valid_cron(sch.cron_expr):
                continue
            try:
                nxt = compute_next_run_at(sch.cron_expr, base=now)
            except Exception:  # noqa: BLE001
                continue
            await storage.update_schedule(engine, sch.id, next_run_at=nxt)

    async def _loop(self) -> None:
        while not self._stopping.is_set():
            try:
                await self._tick()
            except Exception as e:  # noqa: BLE001
                print(f"[scheduler] tick error: {e}", file=sys.stderr, flush=True)
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=TICK_SECONDS)
            except asyncio.TimeoutError:
                pass

    async def _tick(self) -> None:
        engine = await self._handlers.ensure_engine()
        now = time.time()
        due = await storage.list_schedules(
            engine, enabled_only=True, due_before=now,
        )
        for sch in due:
            if sch.id in self._running_ids:
                continue
            self._running_ids.add(sch.id)
            asyncio.create_task(self._fire(sch), name=f"sched-fire-{sch.id[:8]}")

    async def _fire(self, sch: storage.Schedule) -> None:
        """tick 觸發:跑 schedule + 寫回 next_run_at + 推 notification。"""
        try:
            await self._run_schedule_now(sch, mark_run=True)
        finally:
            self._running_ids.discard(sch.id)

    async def _run_schedule_now(
        self, sch: storage.Schedule, *, mark_run: bool,
    ) -> str | None:
        """共享路徑(tick fire 與 run_now 都走這)。"""
        engine = await self._handlers.ensure_engine()
        now = time.time()
        session_id: str | None = None
        status = "ok"
        error: str | None = None
        # 先算 next_run_at,即使 fire 失敗也要推進避免 stuck
        nxt: float | None = None
        try:
            nxt = compute_next_run_at(sch.cron_expr, base=now)
        except Exception as e:  # noqa: BLE001
            error = f"cron parse error: {e}"
            status = "error"
        if status == "ok":
            try:
                session_id = await self._execute_schedule(sch)
            except Exception as e:  # noqa: BLE001
                error = f"{type(e).__name__}: {e}"
                status = "error"
                print(
                    f"[scheduler] fire {sch.id} failed: {e}",
                    file=sys.stderr, flush=True,
                )
        if mark_run:
            try:
                await storage.record_schedule_run(
                    engine, sch.id,
                    last_run_at=now,
                    next_run_at=nxt,
                    last_run_session_id=session_id,
                    status=status,
                    error=error,
                )
            except Exception as e:  # noqa: BLE001
                print(
                    f"[scheduler] record_run failed: {e}",
                    file=sys.stderr, flush=True,
                )
        # 推 notification 給 renderer(無 id frame)
        try:
            await self._handlers.notify({
                "event": "scheduler.fired",
                "data": {
                    "schedule_id": sch.id,
                    "schedule_name": sch.name,
                    "session_id": session_id,
                    "status": status,
                    "error": error,
                    "next_run_at": nxt,
                },
            })
        except Exception as e:  # noqa: BLE001
            print(
                f"[scheduler] notify failed: {e}",
                file=sys.stderr, flush=True,
            )
        return session_id

    async def _execute_schedule(self, sch: storage.Schedule) -> str:
        """組 prompt → 若 target_session_id 有值就送回該既有 session(Loop 模式),
        否則 conv.create + send 開新 session(排程模式)。回實際跑的 session_id。"""
        if sch.trigger_type == "skill":
            prompt = (
                f"請執行 Skill '{sch.payload}'。這是排程任務,請依 Skill 指示完成。"
            )
        else:
            prompt = sch.payload

        # Loop 模式 — 送回既有 session
        if sch.target_session_id:
            send_params: dict[str, Any] = {
                "session_id": sch.target_session_id,
                "prompt": prompt,
                "permission_mode": "act",
            }
            async for _frame in self._handlers.conversation_send(send_params):
                pass
            return sch.target_session_id

        # 排程模式 — 開新 session
        provider = sch.model_provider or "anthropic"
        model = sch.model or "claude-sonnet-4-6"
        create_params: dict[str, Any] = {"provider": provider, "model": model}
        if sch.project_id:
            create_params["project_id"] = sch.project_id
        if sch.workspace_dir:
            create_params["workspace_dir"] = sch.workspace_dir

        new_session_id: str | None = None
        async for frame in self._handlers.conversation_create(create_params):
            if frame.get("event") == "conversation_created":
                data = frame.get("data") or {}
                new_session_id = data.get("session_id")
        if not new_session_id:
            raise RuntimeError("conversation_create did not return session_id")

        # Mark this session 為排程觸發 + 給友善 title
        engine = await self._handlers.ensure_engine()
        try:
            await storage.set_session_scheduled_by(
                engine, new_session_id,
                schedule_id=sch.id, schedule_name=sch.name,
            )
            await storage.update_title_if_empty(
                engine, new_session_id, f"⏱ {sch.name}",
            )
        except Exception as e:  # noqa: BLE001
            print(
                f"[scheduler] mark session failed: {e}",
                file=sys.stderr, flush=True,
            )

        send_params2: dict[str, Any] = {
            "session_id": new_session_id,
            "prompt": prompt,
            "permission_mode": "act",  # 排程跑 = autonomous
        }
        async for _frame in self._handlers.conversation_send(send_params2):
            # drain 全部 frames 直到 final
            pass
        return new_session_id
