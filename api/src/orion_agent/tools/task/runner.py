"""BackgroundTaskRunner — Phase 10。

shared in-memory task registry。Phase 10 範圍 single-instance(global registry);
Phase 10c 改 SQLite-backed 跨 worker。

設計:
- create(subject, description, command):記 TaskRecord(state=pending)
- start(task_id):跑 shell command 在 anyio.create_task_group 內,output 寫 stdout 累積
- update(task_id, ...):改 state / metadata
- get(task_id) / list(filters):查
- stop(task_id):cancel 該 task
- output(task_id):回最近 stdout

state machine:pending → in_progress → (completed | failed | deleted | stopped)
"""

from __future__ import annotations

import asyncio
import contextlib
import shlex
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

import anyio

TaskState = Literal[
    "pending",
    "in_progress",
    "completed",
    "failed",
    "stopped",
    "deleted",
]


@dataclass
class TaskRecord:
    """單一 background task。"""

    id: str
    subject: str
    description: str = ""
    command: str = ""
    """選用 — 若有,start() 時跑這條 shell。Empty → 純 metadata task(由 caller 自己跑)。"""
    state: TaskState = "pending"
    metadata: dict[str, Any] = field(default_factory=dict)
    output: list[str] = field(default_factory=list)
    """累積 stdout / stderr lines。"""
    return_code: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    _task: asyncio.Task[None] | None = None
    """asyncio.Task handle(stop 時 cancel)。"""

    def to_summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "subject": self.subject,
            "description": self.description,
            "state": self.state,
            "metadata": dict(self.metadata),
            "return_code": self.return_code,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class BackgroundTaskRunner:
    """in-memory task registry + runner。"""

    def __init__(self) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        *,
        subject: str,
        description: str = "",
        command: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> TaskRecord:
        async with self._lock:
            tid = uuid4().hex[:12]
            rec = TaskRecord(
                id=tid,
                subject=subject,
                description=description,
                command=command,
                metadata=metadata or {},
            )
            self._tasks[tid] = rec
            return rec

    async def start(self, task_id: str) -> bool:
        """若 task 有 command,spawn asyncio.Task 跑。已 in_progress 不再啟。"""
        rec = self._tasks.get(task_id)
        if rec is None or not rec.command:
            return False
        if rec.state in ("in_progress", "completed", "failed", "stopped", "deleted"):
            return False

        async def _run() -> None:
            rec.state = "in_progress"
            rec.updated_at = datetime.now(UTC)
            try:
                proc = await asyncio.create_subprocess_shell(
                    rec.command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                assert proc.stdout is not None
                while True:
                    chunk = await proc.stdout.readline()
                    if not chunk:
                        break
                    rec.output.append(chunk.decode("utf-8", errors="replace").rstrip("\n"))
                rc = await proc.wait()
                rec.return_code = rc
                rec.state = "completed" if rc == 0 else "failed"
            except asyncio.CancelledError:
                rec.state = "stopped"
                raise
            except Exception as e:  # noqa: BLE001
                rec.output.append(f"[runner error] {type(e).__name__}: {e}")
                rec.state = "failed"
            finally:
                rec.updated_at = datetime.now(UTC)

        rec._task = asyncio.create_task(_run())
        return True

    def get(self, task_id: str) -> TaskRecord | None:
        return self._tasks.get(task_id)

    def list_tasks(
        self,
        *,
        state: TaskState | None = None,
        subject_contains: str | None = None,
    ) -> list[TaskRecord]:
        out: list[TaskRecord] = []
        for r in self._tasks.values():
            if state is not None and r.state != state:
                continue
            if subject_contains and subject_contains.lower() not in r.subject.lower():
                continue
            out.append(r)
        out.sort(key=lambda r: r.created_at, reverse=True)
        return out

    async def update(
        self,
        task_id: str,
        *,
        state: TaskState | None = None,
        subject: str | None = None,
        description: str | None = None,
        metadata_patch: dict[str, Any] | None = None,
    ) -> TaskRecord | None:
        rec = self._tasks.get(task_id)
        if rec is None:
            return None
        if state is not None:
            rec.state = state
        if subject is not None:
            rec.subject = subject
        if description is not None:
            rec.description = description
        if metadata_patch:
            rec.metadata.update(metadata_patch)
        rec.updated_at = datetime.now(UTC)
        return rec

    async def stop(self, task_id: str) -> bool:
        rec = self._tasks.get(task_id)
        if rec is None:
            return False
        if rec._task is not None and not rec._task.done():
            rec._task.cancel()
            with anyio.move_on_after(2), contextlib.suppress(asyncio.CancelledError):
                await rec._task
        if rec.state in ("pending", "in_progress"):
            rec.state = "stopped"
            rec.updated_at = datetime.now(UTC)
        return True

    def output(self, task_id: str, *, max_lines: int = 200) -> list[str]:
        rec = self._tasks.get(task_id)
        if rec is None:
            return []
        return rec.output[-max_lines:]

    def reset(self) -> None:
        """測試用 — 清空。"""
        for rec in self._tasks.values():
            if rec._task is not None and not rec._task.done():
                rec._task.cancel()
        self._tasks.clear()


# ─── global singleton ────────────────────────────────────────────────────


_runner: BackgroundTaskRunner | None = None


def get_runner() -> BackgroundTaskRunner:
    global _runner
    if _runner is None:
        _runner = BackgroundTaskRunner()
    return _runner


def reset_runner() -> None:
    global _runner
    if _runner is not None:
        _runner.reset()
    _runner = None


# silence unused
_ = shlex
