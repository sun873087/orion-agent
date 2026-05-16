"""MCP server supervisor — Phase 31-H。

Long-running async task,定期檢查 McpManager.failed_servers,對每個失敗 server
跑 reconnect 嘗試。指數 backoff,max retries 後放棄(下次 fresh check 重新計次)。

設計:
- Per-server independent state(attempt count、next retry time)
- check_interval 秒檢查一次,失敗 server 跑 backoff 公式決定是否該 retry
- 成功 reconnect → reset attempt count,emit recovered notification callback
- 達 max retries → emit give-up notification callback,該 server 之後不再 retry
  (直到 caller 顯式呼叫 reset_attempts(name) 或 supervisor stop/restart)

Notification 透過 caller-provided callback(避免循環依賴 hook system):

    supervisor = McpSupervisor(manager, on_event=lambda kind, name, msg: ...)

`kind` ∈ {"recovered", "retry_failed", "gave_up"}。

環境變數:
- ORION_MCP_CHECK_INTERVAL_SECONDS  default 5.0
- ORION_MCP_MAX_RETRIES             default 3
- ORION_MCP_BASE_BACKOFF_SECONDS    default 1.0 (1, 2, 4, ...)
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Literal

import structlog

if TYPE_CHECKING:
    from orion_sdk.mcp.manager import McpManager

log = structlog.get_logger(__name__)

EventKind = Literal["recovered", "retry_failed", "gave_up"]
EventCallback = Callable[[EventKind, str, str], Awaitable[None] | None]


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class McpSupervisor:
    """Background task watching McpManager.failed_servers + auto-reconnect。

    Usage:
        async with McpManager(...) as manager:
            supervisor = McpSupervisor(manager)
            task = asyncio.create_task(supervisor.run())
            try:
                # ... do agent work ...
            finally:
                supervisor.stop()
                await task
    """

    def __init__(
        self,
        manager: "McpManager",
        *,
        on_event: EventCallback | None = None,
        check_interval: float | None = None,
        max_retries: int | None = None,
        base_backoff: float | None = None,
    ) -> None:
        self.manager = manager
        self.on_event = on_event
        self.check_interval = check_interval if check_interval is not None else _env_float("ORION_MCP_CHECK_INTERVAL_SECONDS", 5.0)
        self.max_retries = max_retries if max_retries is not None else _env_int("ORION_MCP_MAX_RETRIES", 3)
        self.base_backoff = base_backoff if base_backoff is not None else _env_float("ORION_MCP_BASE_BACKOFF_SECONDS", 1.0)

        # per-server state
        self._attempts: dict[str, int] = {}
        self._next_retry_at: dict[str, float] = {}
        self._gave_up: set[str] = set()

        self._stop_event = asyncio.Event()

    def stop(self) -> None:
        """Signal the supervisor loop to exit at next iteration boundary。"""
        self._stop_event.set()

    def reset_attempts(self, name: str) -> None:
        """重置某 server 的 attempt count(例如 user 從 UI 手動 retry give-up 的 server)。"""
        self._attempts.pop(name, None)
        self._next_retry_at.pop(name, None)
        self._gave_up.discard(name)

    def attempts(self, name: str) -> int:
        """Current attempt count for inspection / tests。"""
        return self._attempts.get(name, 0)

    def has_given_up(self, name: str) -> bool:
        return name in self._gave_up

    async def _emit(self, kind: EventKind, name: str, message: str) -> None:
        if self.on_event is None:
            return
        try:
            result = self.on_event(kind, name, message)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:  # noqa: BLE001
            log.warning("mcp.supervisor.callback_error", error=str(e), kind=kind, name=name)

    async def _check_once(self, now: float) -> None:
        """跑一輪 check,把該 retry 的 server 拉起來。"""
        for name in self.manager.failed_servers:
            if name in self._gave_up:
                continue
            next_retry = self._next_retry_at.get(name, 0.0)
            if now < next_retry:
                continue

            attempt = self._attempts.get(name, 0)
            ok = await self.manager.reconnect(name)
            if ok:
                self._attempts.pop(name, None)
                self._next_retry_at.pop(name, None)
                await self._emit("recovered", name, f"reconnected after {attempt} retries")
                continue

            attempt += 1
            self._attempts[name] = attempt
            err = self.manager.connection_errors.get(name, "unknown error")
            if attempt >= self.max_retries:
                self._gave_up.add(name)
                await self._emit("gave_up", name, f"gave up after {attempt} retries: {err}")
            else:
                backoff = self.base_backoff * (2 ** (attempt - 1))
                self._next_retry_at[name] = now + backoff
                await self._emit(
                    "retry_failed",
                    name,
                    f"attempt {attempt}/{self.max_retries} failed: {err} (retry in {backoff:.1f}s)",
                )

    async def run(self) -> None:
        """Main loop。`stop()` 觸發後在下一個 check boundary 退出。"""
        while not self._stop_event.is_set():
            try:
                await self._check_once(time.monotonic())
            except Exception as e:  # noqa: BLE001
                log.warning("mcp.supervisor.check_error", error=str(e))
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.check_interval,
                )
                # stop_event set → 跳出
                break
            except asyncio.TimeoutError:
                # 正常 wakeup,繼續下一輪
                continue
