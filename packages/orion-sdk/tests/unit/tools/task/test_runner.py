"""BackgroundTaskRunner — create / start command / stop / list / update。"""

from __future__ import annotations

import asyncio

import pytest

from orion_sdk.tools.task.runner import (
    BackgroundTaskRunner,
    get_runner,
    reset_runner,
)


@pytest.fixture(autouse=True)
def _clean() -> None:
    reset_runner()


@pytest.mark.asyncio
async def test_create_no_command() -> None:
    r = BackgroundTaskRunner()
    rec = await r.create(subject="x", description="y")
    assert rec.state == "pending"
    assert rec.command == ""


@pytest.mark.asyncio
async def test_start_runs_command_to_completion() -> None:
    r = BackgroundTaskRunner()
    rec = await r.create(subject="echo", command="echo hello && echo world")
    started = await r.start(rec.id)
    assert started is True
    # wait for completion
    assert rec._task is not None
    await asyncio.wait_for(rec._task, timeout=5.0)
    assert rec.state == "completed"
    assert rec.return_code == 0
    assert any("hello" in line for line in rec.output)


@pytest.mark.asyncio
async def test_start_failed_command() -> None:
    r = BackgroundTaskRunner()
    rec = await r.create(subject="fail", command="exit 7")
    await r.start(rec.id)
    await asyncio.wait_for(rec._task, timeout=5.0)  # type: ignore[arg-type]
    assert rec.state == "failed"
    assert rec.return_code == 7


@pytest.mark.asyncio
async def test_stop_running_task() -> None:
    r = BackgroundTaskRunner()
    rec = await r.create(subject="loop", command="sleep 30")
    await r.start(rec.id)
    await asyncio.sleep(0.1)
    ok = await r.stop(rec.id)
    assert ok is True
    assert rec.state == "stopped"


@pytest.mark.asyncio
async def test_list_filters_by_state() -> None:
    r = BackgroundTaskRunner()
    a = await r.create(subject="a")
    b = await r.create(subject="b")
    await r.update(b.id, state="completed")
    pending = r.list_tasks(state="pending")
    assert {x.id for x in pending} == {a.id}


@pytest.mark.asyncio
async def test_list_filters_by_subject() -> None:
    r = BackgroundTaskRunner()
    a = await r.create(subject="orange")
    b = await r.create(subject="banana")
    matched = r.list_tasks(subject_contains="ban")
    assert {x.id for x in matched} == {b.id}
    _ = a


@pytest.mark.asyncio
async def test_update_metadata_merge() -> None:
    r = BackgroundTaskRunner()
    rec = await r.create(subject="x", metadata={"a": 1})
    await r.update(rec.id, metadata_patch={"b": 2})
    assert rec.metadata == {"a": 1, "b": 2}


@pytest.mark.asyncio
async def test_output_returns_recent_lines() -> None:
    r = BackgroundTaskRunner()
    rec = await r.create(subject="x", command="for i in 1 2 3; do echo line-$i; done")
    await r.start(rec.id)
    await asyncio.wait_for(rec._task, timeout=5.0)  # type: ignore[arg-type]
    out = r.output(rec.id, max_lines=10)
    assert any("line-3" in line for line in out)


@pytest.mark.asyncio
async def test_get_unknown_returns_none() -> None:
    r = BackgroundTaskRunner()
    assert r.get("unknown-id") is None


def test_global_singleton() -> None:
    a = get_runner()
    b = get_runner()
    assert a is b
