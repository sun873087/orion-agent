"""DockerBackend — per-session Docker container 隔離。

對應 Phase 7 spec § 5(主文件 Docker 路線)。

設計:
- 每 conversation 一個 container(image: 預設 `python:3.12-slim`)
- 啟時 `sleep infinity` 保持 alive
- exec 走 `docker exec`,讀寫檔走 `docker cp`(get_archive / put_archive)
- cleanup 停 + 移除 container

**block 操作 wrap 進 anyio.to_thread**(docker SDK 是 sync)。
"""

from __future__ import annotations

import contextlib
import io
import logging
import tarfile
from typing import Any
from uuid import uuid4

import anyio

from orion_sdk.sandbox.protocol import ExecResult, SandboxError

logger = logging.getLogger(__name__)


_DEFAULT_IMAGE = "python:3.12-slim"
_DEFAULT_WORKDIR = "/workspace"
_EXEC_OUTPUT_LIMIT = 30_000


class DockerBackend:
    """每 conversation 一個 Docker container。"""

    name = "docker"

    def __init__(
        self,
        *,
        image: str = _DEFAULT_IMAGE,
        workdir: str = _DEFAULT_WORKDIR,
        container_name: str | None = None,
        memory_mb: int = 512,
        cpu_quota: float = 0.5,
        network_disabled: bool = False,
    ) -> None:
        self.image = image
        self.workdir = workdir
        self.container_name = container_name or f"orion-sandbox-{uuid4().hex[:12]}"
        self.memory_mb = memory_mb
        self.cpu_quota = cpu_quota
        self.network_disabled = network_disabled
        self._container: Any | None = None
        self._client: Any | None = None

    async def _ensure_container(self) -> Any:
        """lazy init — 第一次 exec 才啟 container。"""
        if self._container is not None:
            return self._container

        try:
            import docker  # type: ignore[import-untyped]
        except ImportError as e:
            raise SandboxError("docker package not installed") from e

        def _start() -> Any:
            client = docker.from_env()
            try:
                # 確保 image 存在(沒有就 pull)
                try:
                    client.images.get(self.image)
                except docker.errors.ImageNotFound:
                    logger.info("pulling sandbox image %s", self.image)
                    client.images.pull(self.image)

                container = client.containers.run(
                    self.image,
                    command=["sleep", "infinity"],
                    name=self.container_name,
                    detach=True,
                    working_dir=self.workdir,
                    mem_limit=f"{self.memory_mb}m",
                    nano_cpus=int(self.cpu_quota * 1_000_000_000),
                    network_disabled=self.network_disabled,
                    auto_remove=False,
                    cap_drop=["ALL"],
                    security_opt=["no-new-privileges"],
                )
                # 確保 workdir 存在
                exec_id = client.api.exec_create(
                    container.id, ["mkdir", "-p", self.workdir],
                )
                client.api.exec_start(exec_id, detach=False)
                return client, container
            except Exception:
                client.close()
                raise

        try:
            client, container = await anyio.to_thread.run_sync(_start)
        except Exception as e:  # noqa: BLE001
            raise SandboxError(f"docker container start failed: {e}") from e

        self._client = client
        self._container = container
        return container

    async def exec(
        self,
        argv: list[str],
        *,
        cwd: str | None = None,
        timeout: float = 30.0,
        env: dict[str, str] | None = None,
    ) -> ExecResult:
        container = await self._ensure_container()

        exec_workdir = cwd or self.workdir

        def _run() -> tuple[int, bytes]:
            # docker SDK exec_run 包好 ExecCreate + ExecStart
            exec_result = container.exec_run(
                argv,
                workdir=exec_workdir,
                environment=env,
                demux=False,
                stdout=True,
                stderr=True,
            )
            return exec_result.exit_code or 0, exec_result.output or b""

        try:
            with anyio.move_on_after(timeout) as scope:
                exit_code, raw_output = await anyio.to_thread.run_sync(_run)
            if scope.cancel_called:
                raise SandboxError(f"command timed out after {timeout}s")
        except SandboxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise SandboxError(f"docker exec failed: {e}") from e

        truncated = False
        if len(raw_output) > _EXEC_OUTPUT_LIMIT:
            raw_output = raw_output[:_EXEC_OUTPUT_LIMIT]
            truncated = True

        return ExecResult(
            exit_code=exit_code,
            stdout=raw_output.decode("utf-8", errors="replace"),
            truncated=truncated,
            extra={"container_id": container.id},
        )

    async def read_file(self, path: str) -> bytes:
        container = await self._ensure_container()

        def _read() -> bytes:
            try:
                # get_archive 回 (generator of tar chunks, stat dict)
                stream, _stat = container.get_archive(path)
            except Exception as e:
                raise SandboxError(f"read_file failed: {e}") from e

            buf = io.BytesIO()
            for chunk in stream:
                buf.write(chunk)
            buf.seek(0)
            with tarfile.open(fileobj=buf, mode="r") as tar:
                # tar 內第一個檔(我們只請一個 path)
                names = tar.getnames()
                if not names:
                    raise SandboxError(f"empty archive for {path}")
                f = tar.extractfile(names[0])
                if f is None:
                    raise SandboxError(f"could not extract {path}")
                return f.read()

        try:
            return await anyio.to_thread.run_sync(_read)
        except SandboxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise SandboxError(f"read_file failed: {e}") from e

    async def write_file(self, path: str, data: bytes) -> None:
        import os.path as op

        container = await self._ensure_container()
        parent = op.dirname(path) or "/"
        filename = op.basename(path)

        def _write() -> None:
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w") as tar:
                info = tarfile.TarInfo(name=filename)
                info.size = len(data)
                info.mode = 0o644
                tar.addfile(info, io.BytesIO(data))
            buf.seek(0)
            try:
                container.put_archive(path=parent, data=buf.getvalue())
            except Exception as e:
                raise SandboxError(f"write_file failed: {e}") from e

        try:
            await anyio.to_thread.run_sync(_write)
        except SandboxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise SandboxError(f"write_file failed: {e}") from e

    async def cleanup(self) -> None:
        container = self._container
        client = self._client
        if container is None:
            return

        def _stop() -> None:
            with contextlib.suppress(Exception):
                container.stop(timeout=2)
            with contextlib.suppress(Exception):
                container.remove(force=True)
            if client is not None:
                with contextlib.suppress(Exception):
                    client.close()

        try:
            await anyio.to_thread.run_sync(_stop)
        finally:
            self._container = None
            self._client = None
