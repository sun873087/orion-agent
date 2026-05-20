"""Tests for orion_sdk.mcp.supervisor。

用 FakeManager(實作 failed_servers + reconnect 介面)隔離 supervisor 邏輯,
不依賴實際 MCP transport。
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from orion_sdk.mcp.supervisor import McpSupervisor


class FakeManager:
    """測試 stub。caller 可控制每次 reconnect 成功與否。"""

    def __init__(self, initial_failed: list[str]) -> None:
        self._failed: list[str] = list(initial_failed)
        self.connection_errors: dict[str, str] = {n: "init fail" for n in initial_failed}
        self.reconnect_results: dict[str, list[bool]] = {}
        """name → [bool] 每次 reconnect 的結果 queue,popleft 順序消費。"""
        self.reconnect_calls: list[str] = []

    @property
    def failed_servers(self) -> list[str]:
        return list(self._failed)

    def queue_results(self, name: str, results: list[bool]) -> None:
        self.reconnect_results[name] = list(results)

    async def reconnect(self, name: str) -> bool:
        self.reconnect_calls.append(name)
        results = self.reconnect_results.get(name, [])
        if not results:
            ok = False
        else:
            ok = results.pop(0)
        if ok:
            if name in self._failed:
                self._failed.remove(name)
            self.connection_errors.pop(name, None)
        else:
            if name not in self._failed:
                self._failed.append(name)
            self.connection_errors[name] = "still failing"
        return ok


async def test_recover_on_first_retry() -> None:
    manager = FakeManager(initial_failed=["alpha"])
    manager.queue_results("alpha", [True])

    events: list[tuple[str, str, str]] = []

    async def on_event(kind: str, name: str, msg: str) -> None:
        events.append((kind, name, msg))

    sup = McpSupervisor(manager, on_event=on_event, check_interval=0.01, max_retries=3, base_backoff=0.01)
    await sup._check_once(now=0.0)

    assert manager.reconnect_calls == ["alpha"]
    assert events[0][0] == "recovered"
    assert "alpha" not in manager.failed_servers


async def test_gives_up_after_max_retries() -> None:
    manager = FakeManager(initial_failed=["bad"])
    manager.queue_results("bad", [False, False, False])

    events: list[tuple[str, str, str]] = []

    async def on_event(kind: str, name: str, msg: str) -> None:
        events.append((kind, name, msg))

    sup = McpSupervisor(manager, on_event=on_event, check_interval=0.01, max_retries=3, base_backoff=0.001)

    # 跑 3 次 check,每次都把 next_retry_at 推進到讓下次能跑
    now = 0.0
    for _ in range(3):
        await sup._check_once(now=now)
        now += 10.0 # 確保越過 backoff

    assert sup.attempts("bad") == 3
    assert sup.has_given_up("bad")
    kinds = [e[0] for e in events]
    assert kinds.count("retry_failed") == 2
    assert kinds.count("gave_up") == 1


async def test_backoff_skips_check_until_due() -> None:
    manager = FakeManager(initial_failed=["x"])
    manager.queue_results("x", [False, True])
    sup = McpSupervisor(manager, check_interval=0.01, max_retries=5, base_backoff=1.0)

    # 第一次 check at t=0,失敗 → next_retry_at = 0 + 1 = 1.0
    await sup._check_once(now=0.0)
    assert manager.reconnect_calls == ["x"]

    # t=0.5 還沒到 → skip(不該再 reconnect)
    await sup._check_once(now=0.5)
    assert manager.reconnect_calls == ["x"] # 仍 1 次

    # t=1.5 已過 backoff → retry,這次成功
    await sup._check_once(now=1.5)
    assert manager.reconnect_calls == ["x", "x"]
    assert "x" not in manager.failed_servers


async def test_reset_attempts_lifts_give_up() -> None:
    manager = FakeManager(initial_failed=["z"])
    manager.queue_results("z", [False, False])

    sup = McpSupervisor(manager, check_interval=0.01, max_retries=2, base_backoff=0.001)
    await sup._check_once(now=0.0)
    await sup._check_once(now=10.0)
    assert sup.has_given_up("z")

    # 模擬 user 點 "manual retry"
    sup.reset_attempts("z")
    assert not sup.has_given_up("z")
    assert sup.attempts("z") == 0

    # 給它一個成功 → recovery
    manager.queue_results("z", [True])
    await sup._check_once(now=20.0)
    assert "z" not in manager.failed_servers


async def test_run_stops_on_signal() -> None:
    manager = FakeManager(initial_failed=[])
    sup = McpSupervisor(manager, check_interval=0.05)

    task = asyncio.create_task(sup.run())
    await asyncio.sleep(0.02)
    sup.stop()
    await asyncio.wait_for(task, timeout=1.0)
    assert task.done()


async def test_callback_exception_does_not_crash() -> None:
    manager = FakeManager(initial_failed=["a"])
    manager.queue_results("a", [True])

    def buggy(kind: str, name: str, msg: str) -> None:
        raise RuntimeError("boom")

    sup = McpSupervisor(manager, on_event=buggy, check_interval=0.01, max_retries=1, base_backoff=0.001)
    # 不該 propagate
    await sup._check_once(now=0.0)
    assert "a" not in manager.failed_servers


async def test_sync_callback_supported() -> None:
    manager = FakeManager(initial_failed=["a"])
    manager.queue_results("a", [True])

    seen: list[str] = []

    def sync_cb(kind: str, name: str, msg: str) -> None:
        seen.append(kind)

    sup = McpSupervisor(manager, on_event=sync_cb, check_interval=0.01)
    await sup._check_once(now=0.0)
    assert seen == ["recovered"]
