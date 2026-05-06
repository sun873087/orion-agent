"""HookRegistry — register / dispatch / pre_tool_use 阻擋邏輯。"""

from __future__ import annotations

import pytest

from orion_agent.hooks.events import HookEvent, PostToolUseEvent, PreToolUseEvent
from orion_agent.hooks.registry import HookRegistry


@pytest.mark.asyncio
async def test_no_hooks_returns_true() -> None:
    reg = HookRegistry()
    ok = await reg.dispatch(PreToolUseEvent())
    assert ok is True


@pytest.mark.asyncio
async def test_pre_tool_use_hook_returning_false_blocks() -> None:
    reg = HookRegistry()

    async def deny(_ev: HookEvent) -> bool:
        return False

    reg.register("pre_tool_use", deny)
    ok = await reg.pre_tool_use(PreToolUseEvent())
    assert ok is False


@pytest.mark.asyncio
async def test_pre_tool_use_hook_returning_none_allows() -> None:
    reg = HookRegistry()

    async def passthrough(_ev: HookEvent) -> None:
        return None

    reg.register("pre_tool_use", passthrough)  # type: ignore[arg-type]
    ok = await reg.pre_tool_use(PreToolUseEvent())
    assert ok is True


@pytest.mark.asyncio
async def test_post_tool_use_return_value_ignored() -> None:
    reg = HookRegistry()
    called = []

    async def observer(ev: HookEvent) -> None:
        called.append(ev)
        return None

    reg.register("post_tool_use", observer)  # type: ignore[arg-type]
    await reg.post_tool_use(PostToolUseEvent(result_text="x"))
    assert len(called) == 1


@pytest.mark.asyncio
async def test_clear_removes_all() -> None:
    reg = HookRegistry()

    async def x(_ev: HookEvent) -> bool:
        return False

    reg.register("pre_tool_use", x)
    reg.clear()
    ok = await reg.pre_tool_use(PreToolUseEvent())
    assert ok is True
