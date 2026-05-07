"""SubprocessPool — Phase 10。

asyncio.create_subprocess_exec 每次都 fork,跑 ripgrep / shell 等高頻短命令時
fork overhead(macOS 上常見 5-15ms)會放大。本 pool 維持 N 個 idle worker
process(背景跑 daemon shell),拿到任務 send line / get reply。

注意:**僅適用無狀態、可序列化的 short command**。複雜 stdin / interactive
不該走這條(直接 create_subprocess_exec)。

Phase 10 範圍簡化版:對 `["sh", "-c", <cmd>]` 形式的命令做 pool。
搜尋類(ripgrep)由 caller 自行用 SubprocessPool.exec_simple。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PooledProcess:
    """單一 worker process 的封裝。"""

    proc: asyncio.subprocess.Process
    in_use: bool = False
    """True 當前正在跑命令(避免重用)。"""

    n_runs: int = 0


@dataclass
class _PoolStats:
    hits: int = 0
    """從 pool 取 worker 成功的次數。"""

    misses: int = 0
    """pool 全 busy → fallback 直 fork 的次數。"""

    spawned: int = 0
    """累計 spawn 過幾個 worker(含 reset 後重 spawn)。"""


class SubprocessPool:
    """簡單版:啟 N 個 long-lived `sh` worker,exec_simple 在其中跑 oneliner。

    若 N 個全 busy,fallback 到直接 create_subprocess_shell。
    Phase 10b 可改 work-stealing / 排隊。
    """

    def __init__(self, *, size: int = 4) -> None:
        self.size = size
        self._workers: list[PooledProcess] = []
        self._lock = asyncio.Lock()
        self.stats = _PoolStats()
        self._fallback_uses_pool = False

    async def _ensure_workers(self) -> None:
        async with self._lock:
            while len(self._workers) < self.size:
                try:
                    proc = await asyncio.create_subprocess_exec(
                        "/bin/sh",
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                    )
                except OSError as e:
                    logger.warning("subprocess pool: failed to spawn /bin/sh: %s", e)
                    return
                self._workers.append(PooledProcess(proc=proc))
                self.stats.spawned += 1

    def _try_acquire(self) -> PooledProcess | None:
        for w in self._workers:
            if not w.in_use and w.proc.returncode is None:
                w.in_use = True
                return w
        return None

    async def exec_simple(self, command: str, *, timeout: float = 10.0) -> tuple[int, str]:
        """跑 oneliner(`sh -c command`),回 (rc, combined_stdout_stderr)。

        Pool busy / 失敗 → fallback create_subprocess_shell(算 stats.misses)。
        """
        await self._ensure_workers()

        # Pool worker 路徑:寫一個 sentinel 接結果。簡化版:每次新 sub-shell。
        # (long-lived shell 維持 stdin alive 但要 sentinel 抓 rc;為簡化先 fallback。)
        # → Phase 10c 改真 sentinel-based 重用。Phase 10 範圍只 stat 框架。
        worker = self._try_acquire()
        if worker is not None:
            try:
                self.stats.hits += 1
                # 暫時做法:即使有 worker,還是 fork。Phase 10c 改 sentinel-based。
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                try:
                    stdout_b, _ = await asyncio.wait_for(
                        proc.communicate(), timeout=timeout,
                    )
                except TimeoutError:
                    proc.kill()
                    return -1, f"<timeout after {timeout}s>"
                rc = proc.returncode if proc.returncode is not None else -1
                return rc, stdout_b.decode("utf-8", errors="replace")
            finally:
                worker.in_use = False
                worker.n_runs += 1
        else:
            self.stats.misses += 1
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                stdout_b, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except TimeoutError:
                proc.kill()
                return -1, f"<timeout after {timeout}s>"
            rc = proc.returncode if proc.returncode is not None else -1
            return rc, stdout_b.decode("utf-8", errors="replace")

    async def shutdown(self) -> None:
        for w in self._workers:
            with contextlib.suppress(ProcessLookupError):
                w.proc.terminate()
        for w in self._workers:
            with contextlib.suppress(TimeoutError, ProcessLookupError):
                await asyncio.wait_for(w.proc.wait(), timeout=2)
        self._workers.clear()


# ─── global singleton ────────────────────────────────────────────────────


_pool: SubprocessPool | None = None


def get_pool(*, size: int = 4) -> SubprocessPool:
    global _pool
    if _pool is None:
        _pool = SubprocessPool(size=size)
    return _pool


def reset_pool() -> None:
    global _pool
    _pool = None
