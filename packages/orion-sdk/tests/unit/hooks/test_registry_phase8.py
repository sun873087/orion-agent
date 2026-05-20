"""HookRegistry — fire / fire_pre_tool_use / fire_user_prompt_submit。"""

from __future__ import annotations

import pytest

from orion_sdk.hooks.events import (
    PreToolUseEvent,
    PreToolUseResult,
    UserPromptSubmitEvent,
    UserPromptSubmitResult,
)
from orion_sdk.hooks.registry import HookRegistry


@pytest.mark.asyncio
async def test_fire_returns_results() -> None:
    reg = HookRegistry()

    async def hook_a(_ev: object) -> str:
        return "a"

    async def hook_b(_ev: object) -> str:
        return "b"

    reg.register("PreToolUse", hook_a)
    reg.register("PreToolUse", hook_b)
    out = await reg.fire(PreToolUseEvent())
    assert out == ["a", "b"]


@pytest.mark.asyncio
async def test_fire_swallows_exception() -> None:
    reg = HookRegistry()

    async def crash(_ev: object) -> None:
        raise ValueError("boom")

    async def ok(_ev: object) -> str:
        return "ok"

    reg.register("PreToolUse", crash)
    reg.register("PreToolUse", ok)
    out = await reg.fire(PreToolUseEvent())
    assert out == [None, "ok"]


@pytest.mark.asyncio
async def test_fire_pre_tool_use_abort_via_result() -> None:
    reg = HookRegistry()

    async def deny(_ev: object) -> PreToolUseResult:
        return PreToolUseResult(abort=True, abort_reason="bad")

    reg.register("PreToolUse", deny)
    res = await reg.fire_pre_tool_use(PreToolUseEvent())
    assert res.abort is True
    assert res.abort_reason == "bad"


@pytest.mark.asyncio
async def test_fire_pre_tool_use_abort_via_false() -> None:
    reg = HookRegistry()

    async def deny(_ev: object) -> bool:
        return False

    reg.register("PreToolUse", deny)
    res = await reg.fire_pre_tool_use(PreToolUseEvent())
    assert res.abort is True


@pytest.mark.asyncio
async def test_fire_pre_tool_use_modified_input_last_wins() -> None:
    reg = HookRegistry()

    async def first(_ev: object) -> PreToolUseResult:
        return PreToolUseResult(modified_input={"x": 1})

    async def second(_ev: object) -> PreToolUseResult:
        return PreToolUseResult(modified_input={"x": 2})

    reg.register("PreToolUse", first)
    reg.register("PreToolUse", second)
    res = await reg.fire_pre_tool_use(PreToolUseEvent())
    assert res.abort is False
    assert res.modified_input == {"x": 2}


@pytest.mark.asyncio
async def test_fire_user_prompt_submit_join_context() -> None:
    reg = HookRegistry()

    async def one(_ev: object) -> UserPromptSubmitResult:
        return UserPromptSubmitResult(additional_context="part1")

    async def two(_ev: object) -> UserPromptSubmitResult:
        return UserPromptSubmitResult(additional_context="part2")

    reg.register("UserPromptSubmit", one)
    reg.register("UserPromptSubmit", two)
    res = await reg.fire_user_prompt_submit(UserPromptSubmitEvent(prompt="x"))
    assert res.abort is False
    assert res.additional_context == "part1\n\npart2"


@pytest.mark.asyncio
async def test_fire_user_prompt_submit_abort() -> None:
    reg = HookRegistry()

    async def deny(_ev: object) -> UserPromptSubmitResult:
        return UserPromptSubmitResult(abort=True, abort_reason="nope")

    reg.register("UserPromptSubmit", deny)
    res = await reg.fire_user_prompt_submit(UserPromptSubmitEvent(prompt="x"))
    assert res.abort is True
    assert res.abort_reason == "nope"


@pytest.mark.asyncio
async def test_unregister() -> None:
    reg = HookRegistry()

    async def h(_ev: object) -> None:
        return None

    reg.register("PreToolUse", h)
    assert reg.count("PreToolUse") == 1
    assert reg.unregister("PreToolUse", h) is True
    assert reg.count("PreToolUse") == 0
    assert reg.unregister("PreToolUse", h) is False # no-op
