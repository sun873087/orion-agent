"""DockerBackend — 連 host docker daemon 的整合風格測試。

無 Docker daemon → 全部 skip。CI 內若未啟 docker 不該 fail。
"""

from __future__ import annotations

import pytest

docker = pytest.importorskip("docker")


def _docker_available() -> bool:
    try:
        client = docker.from_env()
        client.ping()
    except Exception:  # noqa: BLE001
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _docker_available(), reason="docker daemon not reachable",
)


@pytest.mark.anyio
async def test_docker_exec_echo() -> None:
    from orion_sdk.sandbox.docker_backend import DockerBackend

    backend = DockerBackend(image="python:3.12-slim")
    try:
        res = await backend.exec(["/bin/sh", "-c", "echo hi"])
        assert res.exit_code == 0
        assert res.stdout.strip() == "hi"
    finally:
        await backend.cleanup()


@pytest.mark.anyio
async def test_docker_write_read_roundtrip() -> None:
    from orion_sdk.sandbox.docker_backend import DockerBackend

    backend = DockerBackend(image="python:3.12-slim")
    try:
        await backend.write_file("/tmp/orion_test.txt", b"hello docker")
        data = await backend.read_file("/tmp/orion_test.txt")
        assert data == b"hello docker"
    finally:
        await backend.cleanup()
