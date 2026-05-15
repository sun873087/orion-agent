"""LocalBackend 行為:exec / read_file / write_file / cleanup。"""

from __future__ import annotations

from pathlib import Path

import pytest

from orion_sdk.sandbox.local import LocalBackend
from orion_sdk.sandbox.protocol import SandboxBackend, SandboxError


def test_local_satisfies_protocol() -> None:
    assert isinstance(LocalBackend(), SandboxBackend)
    assert LocalBackend().name == "local"


@pytest.mark.anyio
async def test_exec_echo_ok() -> None:
    backend = LocalBackend()
    res = await backend.exec(["/bin/sh", "-c", "echo hello"])
    assert res.exit_code == 0
    assert res.stdout.strip() == "hello"
    assert res.truncated is False


@pytest.mark.anyio
async def test_exec_exit_nonzero() -> None:
    backend = LocalBackend()
    res = await backend.exec(["/bin/sh", "-c", "exit 7"])
    assert res.exit_code == 7


@pytest.mark.anyio
async def test_exec_relative_cwd_rejected() -> None:
    backend = LocalBackend()
    with pytest.raises(SandboxError):
        await backend.exec(["/bin/sh", "-c", "true"], cwd="relative/dir")


@pytest.mark.anyio
async def test_exec_timeout() -> None:
    backend = LocalBackend()
    with pytest.raises(SandboxError):
        await backend.exec(["/bin/sh", "-c", "sleep 5"], timeout=0.3)


@pytest.mark.anyio
async def test_read_write_file_roundtrip(tmp_path: Path) -> None:
    backend = LocalBackend()
    target = tmp_path / "x.txt"
    await backend.write_file(str(target), b"hello orion")
    data = await backend.read_file(str(target))
    assert data == b"hello orion"


@pytest.mark.anyio
async def test_write_relative_path_rejected() -> None:
    backend = LocalBackend()
    with pytest.raises(SandboxError):
        await backend.write_file("relative.txt", b"x")


@pytest.mark.anyio
async def test_write_missing_parent(tmp_path: Path) -> None:
    backend = LocalBackend()
    with pytest.raises(SandboxError):
        await backend.write_file(
            str(tmp_path / "no_such_dir" / "x.txt"), b"x",
        )


@pytest.mark.anyio
async def test_cleanup_noop() -> None:
    backend = LocalBackend()
    await backend.cleanup()
    await backend.cleanup()  # idempotent
