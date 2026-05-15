"""LocalBackend — 無隔離,直接走 host。

對應 Phase 1-6 既有行為(BashTool 直接 anyio.open_process,FileWriteTool 直接 Path.write_bytes)。
LocalBackend 把這些行為包進 SandboxBackend interface,讓 proxy_tools 統一接口。

**生產環境慎用** — 任意 user 輸入都能讀/寫 host fs,沒隔離。Docker / K8s backend 才安全。
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

import anyio

from orion_sdk.sandbox.protocol import ExecResult, SandboxError

_EXEC_OUTPUT_LIMIT = 30_000


class LocalBackend:
    """直接動 host fs / shell。預設 backend。"""

    name = "local"

    async def exec(
        self,
        argv: list[str],
        *,
        cwd: str | None = None,
        timeout: float = 30.0,
        env: dict[str, str] | None = None,
    ) -> ExecResult:
        """anyio subprocess 跑 argv。output 截 30KB。"""
        if cwd is not None and not os.path.isabs(cwd):
            raise SandboxError(f"cwd must be absolute: {cwd!r}")

        merged_env: dict[str, str] | None = None
        if env is not None:
            merged_env = {**os.environ, **env}

        try:
            with anyio.move_on_after(timeout) as scope:
                process = await anyio.open_process(
                    argv,
                    stdout=-1,  # PIPE
                    stderr=-2,  # STDOUT(合併)
                    cwd=cwd,
                    env=merged_env,
                )
                output_chunks: list[bytes] = []
                bytes_total = 0
                truncated = False

                async def read_stdout() -> None:
                    nonlocal bytes_total, truncated
                    if process.stdout is None:
                        return
                    async for chunk in process.stdout:
                        if bytes_total + len(chunk) > _EXEC_OUTPUT_LIMIT:
                            keep = _EXEC_OUTPUT_LIMIT - bytes_total
                            if keep > 0:
                                output_chunks.append(chunk[:keep])
                                bytes_total += keep
                            truncated = True
                            break
                        output_chunks.append(chunk)
                        bytes_total += len(chunk)

                async with anyio.create_task_group() as tg:
                    tg.start_soon(read_stdout)
                    await process.wait()
                    tg.cancel_scope.cancel()

            if scope.cancel_called:
                with contextlib.suppress(ProcessLookupError):
                    if process.returncode is None:
                        process.terminate()
                        with anyio.move_on_after(2):
                            await process.wait()
                        if process.returncode is None:
                            process.kill()
                raise SandboxError(f"command timed out after {timeout}s")
        except SandboxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise SandboxError(f"local exec failed: {type(e).__name__}: {e}") from e

        output = b"".join(output_chunks).decode("utf-8", errors="replace")
        return ExecResult(
            exit_code=process.returncode or 0,
            stdout=output,
            truncated=truncated,
        )

    async def read_file(self, path: str) -> bytes:
        p = Path(path)
        if not p.is_absolute():
            raise SandboxError(f"path must be absolute: {path!r}")
        try:
            return await anyio.to_thread.run_sync(p.read_bytes)
        except OSError as e:
            raise SandboxError(f"read failed: {e}") from e

    async def write_file(self, path: str, data: bytes) -> None:
        p = Path(path)
        if not p.is_absolute():
            raise SandboxError(f"path must be absolute: {path!r}")
        if not p.parent.exists():
            raise SandboxError(f"parent does not exist: {p.parent}")
        try:
            await anyio.to_thread.run_sync(lambda: p.write_bytes(data))
        except OSError as e:
            raise SandboxError(f"write failed: {e}") from e

    async def cleanup(self) -> None:
        """no-op — local 沒資源要清。"""
        return None
