"""run_one_tool — find / parse / preHook / canUseTool / postHook 流程。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import TextEvent, ToolEvent, ToolInput
from orion_sdk.core.tool_execution import (
    ToolProgressUpdate,
    ToolResultUpdate,
    run_one_tool,
)
from orion_sdk.hooks.events import PostToolUseEvent
from orion_sdk.hooks.registry import HookRegistry
from orion_sdk.permissions.decisions import (
    PermissionDecision,
    PermissionResult,
    always_allow,
    always_deny,
)


class _EchoInput(ToolInput):
    text: str


class _EchoTool:
    name = "Echo"
    description = "echo input back"
    input_schema = _EchoInput

    async def call(
        self, input: _EchoInput, ctx: AgentContext  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        yield TextEvent(text=f"echo: {input.text}")

    def is_concurrency_safe(self, _: _EchoInput) -> bool:
        return True

    def is_read_only(self, _: _EchoInput) -> bool:
        return True

    def max_result_size_chars(self) -> int | float:
        return 1000


class _BoomTool:
    name = "Boom"
    description = "raises"
    input_schema = _EchoInput

    async def call(
        self, input: _EchoInput, ctx: AgentContext  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        raise RuntimeError("kaboom")
        yield  # unreachable

    def is_concurrency_safe(self, _: _EchoInput) -> bool:
        return False

    def is_read_only(self, _: _EchoInput) -> bool:
        return False

    def max_result_size_chars(self) -> int | float:
        return 1000


@pytest.mark.asyncio
async def test_unknown_tool_returns_synthetic_error() -> None:
    updates = [
        u
        async for u in run_one_tool(
            "id1", "DoesNotExist", {},
            tools_by_name={},
            can_use_tool=always_allow,
            hooks=HookRegistry(),
            ctx=AgentContext(),
        )
    ]
    # 1 ToolUseStartUpdate + 1 ToolResultUpdate
    assert len(updates) == 2
    final = updates[-1]
    assert isinstance(final, ToolResultUpdate)
    assert final.is_error
    assert "not found" in str(final.message.content)


@pytest.mark.asyncio
async def test_invalid_input_returns_error() -> None:
    """missing required field → ValidationError 包成 synthetic error。"""
    tool = _EchoTool()
    updates = [
        u
        async for u in run_one_tool(
            "id1", "Echo", {},  # no text
            tools_by_name={"Echo": tool},  # type: ignore[dict-item]
            can_use_tool=always_allow,
            hooks=HookRegistry(),
            ctx=AgentContext(),
        )
    ]
    final = updates[-1]
    assert isinstance(final, ToolResultUpdate)
    assert final.is_error


@pytest.mark.asyncio
async def test_permission_deny_blocks() -> None:
    tool = _EchoTool()
    updates = [
        u
        async for u in run_one_tool(
            "id1", "Echo", {"text": "x"},
            tools_by_name={"Echo": tool},  # type: ignore[dict-item]
            can_use_tool=always_deny,
            hooks=HookRegistry(),
            ctx=AgentContext(),
        )
    ]
    final = updates[-1]
    assert isinstance(final, ToolResultUpdate)
    assert final.is_error
    assert "not permitted" in str(final.message.content).lower()


@pytest.mark.asyncio
async def test_pre_hook_can_block() -> None:
    tool = _EchoTool()
    hooks = HookRegistry()

    async def deny_hook(_event: object) -> bool:
        return False

    hooks.register("PreToolUse", deny_hook)

    updates = [
        u
        async for u in run_one_tool(
            "id1", "Echo", {"text": "x"},
            tools_by_name={"Echo": tool},  # type: ignore[dict-item]
            can_use_tool=always_allow,
            hooks=hooks,
            ctx=AgentContext(),
        )
    ]
    final = updates[-1]
    assert isinstance(final, ToolResultUpdate)
    assert final.is_error
    assert "hook" in str(final.message.content).lower()


@pytest.mark.asyncio
async def test_tool_exception_caught_not_propagated() -> None:
    tool = _BoomTool()
    updates = [
        u
        async for u in run_one_tool(
            "id1", "Boom", {"text": "x"},
            tools_by_name={"Boom": tool},  # type: ignore[dict-item]
            can_use_tool=always_allow,
            hooks=HookRegistry(),
            ctx=AgentContext(),
        )
    ]
    final = updates[-1]
    assert isinstance(final, ToolResultUpdate)
    assert final.is_error
    assert "kaboom" in str(final.message.content)


@pytest.mark.asyncio
async def test_happy_path_yields_progress_then_result() -> None:
    tool = _EchoTool()
    hooks = HookRegistry()
    post_calls: list[PostToolUseEvent] = []

    async def post_observer(ev: object) -> None:
        if isinstance(ev, PostToolUseEvent):
            post_calls.append(ev)

    hooks.register("PostToolUse", post_observer)  # type: ignore[arg-type]

    updates = [
        u
        async for u in run_one_tool(
            "id1", "Echo", {"text": "hi"},
            tools_by_name={"Echo": tool},  # type: ignore[dict-item]
            can_use_tool=always_allow,
            hooks=hooks,
            ctx=AgentContext(),
        )
    ]
    progress = [u for u in updates if isinstance(u, ToolProgressUpdate)]
    final = updates[-1]
    assert len(progress) >= 1
    assert isinstance(final, ToolResultUpdate)
    assert not final.is_error
    assert "echo: hi" in str(final.message.content)
    assert len(post_calls) == 1
    assert post_calls[0].is_error is False


@pytest.mark.asyncio
async def test_custom_permission_with_reason() -> None:
    async def my_policy(
        tool: object,  # noqa: ARG001
        input: dict[str, object],  # noqa: ARG001
        ctx: AgentContext,  # noqa: ARG001
    ) -> PermissionResult:
        return PermissionResult(decision=PermissionDecision.DENY, reason="dev mode")

    updates = [
        u
        async for u in run_one_tool(
            "id1", "Echo", {"text": "x"},
            tools_by_name={"Echo": _EchoTool()},  # type: ignore[dict-item]
            can_use_tool=my_policy,
            hooks=HookRegistry(),
            ctx=AgentContext(),
        )
    ]
    final = updates[-1]
    assert isinstance(final, ToolResultUpdate)
    assert "dev mode" in final.extra_notes[0]
