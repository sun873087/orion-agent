"""fork_context_for_subagent + release_subagent。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import anyio
import pytest

from orion_sdk.core.state import AgentContext
from orion_sdk.sandbox.protocol import ExecResult
from orion_sdk.sandbox.sub_agent_isolation import (
    fork_context_for_subagent,
    release_subagent,
)


@dataclass
class _FakeSandbox:
    name: str = "fake"
    cleanup_count: int = 0
    files: dict[str, bytes] = field(default_factory=dict)

    async def exec(self, argv: list[str], **kwargs: Any) -> ExecResult:  # noqa: ARG002
        return ExecResult(exit_code=0, stdout="")

    async def read_file(self, path: str) -> bytes:
        return self.files.get(path, b"")

    async def write_file(self, path: str, data: bytes) -> None:
        self.files[path] = data

    async def cleanup(self) -> None:
        self.cleanup_count += 1


@pytest.mark.asyncio
async def test_fork_creates_new_session_id_and_abort() -> None:
    parent = AgentContext(user_id="u1")
    parent.abort_event.set()  # parent aborted

    handle = await fork_context_for_subagent(parent)
    assert handle.ctx.session_id != parent.session_id
    # 子 abort 獨立(parent set 但 child 沒)
    assert not handle.ctx.abort_event.is_set()
    # depth +1
    assert handle.ctx.sub_agent_depth == parent.sub_agent_depth + 1
    # cwd / user_id 繼承
    assert handle.ctx.cwd == parent.cwd
    assert handle.ctx.user_id == parent.user_id


@pytest.mark.asyncio
async def test_fork_with_factory_creates_new_sandbox() -> None:
    parent = AgentContext()

    def factory() -> _FakeSandbox:
        return _FakeSandbox()

    handle = await fork_context_for_subagent(parent, sandbox_factory=factory)
    assert handle.sandbox is not None
    assert isinstance(handle.sandbox, _FakeSandbox)
    assert handle.ctx.sandbox_backend is handle.sandbox


@pytest.mark.asyncio
async def test_fork_with_async_factory() -> None:
    parent = AgentContext()

    async def factory() -> _FakeSandbox:
        return _FakeSandbox(name="async-built")

    handle = await fork_context_for_subagent(parent, sandbox_factory=factory)
    assert isinstance(handle.sandbox, _FakeSandbox)
    assert handle.sandbox.name == "async-built"


@pytest.mark.asyncio
async def test_inherit_sandbox_no_new_creation() -> None:
    parent_sb = _FakeSandbox()
    parent = AgentContext(sandbox_backend=parent_sb)

    def factory() -> _FakeSandbox:
        raise AssertionError("should not be called when inherit_sandbox=True")

    handle = await fork_context_for_subagent(
        parent, sandbox_factory=factory, inherit_sandbox=True,
    )
    # handle.sandbox = None(共用),但 ctx.sandbox_backend 指 parent 的
    assert handle.sandbox is None
    assert handle.ctx.sandbox_backend is parent_sb


@pytest.mark.asyncio
async def test_release_calls_cleanup_when_new_sandbox() -> None:
    parent = AgentContext()
    handle = await fork_context_for_subagent(parent, sandbox_factory=_FakeSandbox)
    sb = handle.sandbox
    assert isinstance(sb, _FakeSandbox)
    await release_subagent(handle)
    assert sb.cleanup_count == 1


@pytest.mark.asyncio
async def test_release_noop_when_inherit_sandbox() -> None:
    parent_sb = _FakeSandbox()
    parent = AgentContext(sandbox_backend=parent_sb)
    handle = await fork_context_for_subagent(parent, inherit_sandbox=True)
    await release_subagent(handle)
    # 不該動 parent 的 sandbox cleanup count
    assert parent_sb.cleanup_count == 0


@pytest.mark.asyncio
async def test_independent_abort_event() -> None:
    parent = AgentContext()
    handle = await fork_context_for_subagent(parent)
    # set parent → child 不受影響
    parent.abort_event.set()
    assert not handle.ctx.abort_event.is_set()
    # set child → parent 不受影響
    handle.ctx.abort_event.set()
    # parent 已經 set 過,維持 set,但這代表 set 兩個獨立 Event
    assert isinstance(parent.abort_event, anyio.Event)
    assert isinstance(handle.ctx.abort_event, anyio.Event)
    assert parent.abort_event is not handle.ctx.abort_event
