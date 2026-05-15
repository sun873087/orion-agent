"""Sandboxed proxy tools — 用 in-memory FakeBackend 驗證走 backend、不動 host。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent
from orion_sdk.sandbox.protocol import ExecResult, SandboxBackend
from orion_sdk.sandbox.proxy_tools import (
    SandboxedBashTool,
    SandboxedFileEditTool,
    SandboxedFileReadTool,
    SandboxedFileWriteTool,
    build_sandboxed_tools,
)
from orion_sdk.tools.file.edit import FileEditInput
from orion_sdk.tools.file.read import FileReadInput
from orion_sdk.tools.file.write import FileWriteInput
from orion_sdk.tools.shell.bash import BashInput


@dataclass
class FakeBackend:
    """記錄 call,可預設 read 內容。"""

    name: str = "fake"
    files: dict[str, bytes] = field(default_factory=dict)
    exec_calls: list[list[str]] = field(default_factory=list)
    cleanup_called: int = 0
    next_exit_code: int = 0
    next_stdout: str = "ok"

    async def exec(
        self,
        argv: list[str],
        *,
        cwd: str | None = None,
        timeout: float = 30.0,
        env: dict[str, str] | None = None,
    ) -> ExecResult:
        del cwd, timeout, env
        self.exec_calls.append(argv)
        return ExecResult(exit_code=self.next_exit_code, stdout=self.next_stdout)

    async def read_file(self, path: str) -> bytes:
        return self.files[path]

    async def write_file(self, path: str, data: bytes) -> None:
        self.files[path] = data

    async def cleanup(self) -> None:
        self.cleanup_called += 1


def test_fake_backend_protocol() -> None:
    assert isinstance(FakeBackend(), SandboxBackend)


async def _collect(it: AsyncIterator[ToolEvent]) -> list[ToolEvent]:
    return [ev async for ev in it]


def _ctx() -> AgentContext:
    return AgentContext(feature_flags={})


@pytest.mark.anyio
async def test_bash_routes_through_backend() -> None:
    fake = FakeBackend(next_stdout="hi")
    tool = SandboxedBashTool(fake)
    events = await _collect(
        tool.call(BashInput(command="echo hi"), _ctx()),
    )
    assert fake.exec_calls == [["/bin/bash", "-c", "echo hi"]]
    assert any(isinstance(e, TextEvent) and "hi" in e.text for e in events)


@pytest.mark.anyio
async def test_bash_nonzero_exit_yields_error() -> None:
    fake = FakeBackend(next_exit_code=2, next_stdout="boom")
    tool = SandboxedBashTool(fake)
    events = await _collect(tool.call(BashInput(command="false"), _ctx()))
    assert any(isinstance(e, ErrorEvent) for e in events)


@pytest.mark.anyio
async def test_read_routes_through_backend() -> None:
    fake = FakeBackend(files={"/x.txt": b"line1\nline2"})
    tool = SandboxedFileReadTool(fake)
    events = await _collect(
        tool.call(FileReadInput(path="/x.txt", offset=0, limit=10), _ctx()),
    )
    text = next(e.text for e in events if isinstance(e, TextEvent))
    assert "line1" in text
    assert "line2" in text


@pytest.mark.anyio
async def test_write_routes_through_backend() -> None:
    fake = FakeBackend()
    tool = SandboxedFileWriteTool(fake)
    events = await _collect(
        tool.call(FileWriteInput(path="/y.txt", content="zzz"), _ctx()),
    )
    assert fake.files["/y.txt"] == b"zzz"
    assert any(isinstance(e, TextEvent) for e in events)


@pytest.mark.anyio
async def test_edit_routes_through_backend() -> None:
    fake = FakeBackend(files={"/z.txt": b"foo bar"})
    tool = SandboxedFileEditTool(fake)
    events = await _collect(
        tool.call(
            FileEditInput(path="/z.txt", old_string="foo", new_string="qux"),
            _ctx(),
        ),
    )
    assert fake.files["/z.txt"] == b"qux bar"
    assert any(isinstance(e, TextEvent) for e in events)


@pytest.mark.anyio
async def test_edit_old_not_found() -> None:
    fake = FakeBackend(files={"/z.txt": b"foo"})
    tool = SandboxedFileEditTool(fake)
    events = await _collect(
        tool.call(
            FileEditInput(path="/z.txt", old_string="nope", new_string="x"),
            _ctx(),
        ),
    )
    assert any(isinstance(e, ErrorEvent) for e in events)


def test_build_sandboxed_tools_count() -> None:
    fake = FakeBackend()
    tools = build_sandboxed_tools(fake)
    names = {getattr(t, "name", None) for t in tools}
    assert names == {"Bash", "Read", "Write", "Edit"}
