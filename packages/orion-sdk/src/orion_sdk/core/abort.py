"""Abort 共用 helper — 把 ctx.abort_event 連到 anyio cancel scope。

Phase 16:provider.stream() / long-running tool 在中途即時收到 abort_event 並收手。

Pattern:
    async with abort_aware_scope(ctx) as scope:
        await long_running_op()
    if scope.cancel_called:
        # aborted

或更原語的:
    async with anyio.create_task_group() as tg:
        tg.start_soon(watch_abort, tg.cancel_scope, ctx.abort_event)
        await long_running_op()
        tg.cancel_scope.cancel()  # 正常結束時取消 watcher
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

import anyio


async def _watch_abort(
    scope: anyio.CancelScope,
    abort_event: anyio.Event,
    body_done: anyio.Event,
    poll_interval: float,
) -> None:
    """背景 task:輪詢 abort_event 或 body_done,前者觸發 → cancel scope。"""
    while not abort_event.is_set() and not body_done.is_set():
        await anyio.sleep(poll_interval)
    if abort_event.is_set():
        scope.cancel()


@contextlib.asynccontextmanager
async def abort_aware_scope(
    abort_event: anyio.Event,
    *,
    poll_interval: float = 0.05,
) -> AsyncIterator[anyio.CancelScope]:
    """Context manager:body 跑到一半若 abort_event.set() 則整個 scope 被 cancel。

    用法:
        async with abort_aware_scope(ctx.abort_event) as scope:
            async for ev in provider.stream(...):
                ...
        if scope.cancel_called:
            # 中途被 abort

    內部開一個 task group + watcher task。watcher 同時監看 abort_event 和 body_done:
    - abort_event 先 set → cancel 整個 scope(body 被中斷)
    - body_done 先 set(body 正常結束)→ watcher 安靜退出,scope 未被 cancel
    """
    body_done = anyio.Event()
    async with anyio.create_task_group() as tg:
        tg.start_soon(_watch_abort, tg.cancel_scope, abort_event, body_done, poll_interval)
        try:
            yield tg.cancel_scope
        finally:
            body_done.set()
