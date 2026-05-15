"""query_loop 終止條件:natural_stop / max_turns_reached / aborted。"""

from __future__ import annotations

import pytest

from orion_sdk.core.query_loop import (
    LoopTerminated,
    QueryParams,
    query_loop,
)
from orion_sdk.core.state import AgentContext
from orion_sdk.hooks.registry import HookRegistry
from orion_sdk.permissions.decisions import always_allow
from tests.conftest import MockProvider, MockTurn


@pytest.mark.asyncio
async def test_natural_stop_when_no_tool_use() -> None:
    """模型只回 text(無 tool_use)→ Terminal natural_stop。"""
    provider = MockProvider(turns=[MockTurn(text="Hi there")])
    params = QueryParams(
        provider=provider,  # type: ignore[arg-type]
        system_prompt="be brief",
        tools=[],
        can_use_tool=always_allow,
        hooks=HookRegistry(),
        initial_messages=[],
    )

    events = [ev async for ev in query_loop(params, AgentContext())]
    terminals = [ev for ev in events if isinstance(ev, LoopTerminated)]
    assert len(terminals) == 1
    assert terminals[0].transition.reason == "natural_stop"
    assert terminals[0].total_turns == 1


@pytest.mark.asyncio
async def test_max_turns_reached() -> None:
    """模型不停 yield tool_use → 撞 max_turns 強制終止。"""
    # 5 個 tool_use turns(每輪叫不存在的 tool,會回 synthetic error,模型再被叫)
    provider = MockProvider(turns=[
        MockTurn(text="t1", tool_uses=[("a", "Missing", {})]),
        MockTurn(text="t2", tool_uses=[("b", "Missing", {})]),
        MockTurn(text="t3", tool_uses=[("c", "Missing", {})]),
    ])
    params = QueryParams(
        provider=provider,  # type: ignore[arg-type]
        system_prompt="x",
        tools=[],
        can_use_tool=always_allow,
        hooks=HookRegistry(),
        initial_messages=[],
        max_turns=2,
    )

    events = [ev async for ev in query_loop(params, AgentContext())]
    terminals = [ev for ev in events if isinstance(ev, LoopTerminated)]
    assert terminals[0].transition.reason == "max_turns_reached"
    assert terminals[0].total_turns == 2


@pytest.mark.asyncio
async def test_aborted_via_ctx() -> None:
    """ctx.abort_event set 在開始前 → Terminal aborted,turn=0。"""
    provider = MockProvider(turns=[MockTurn(text="hi")])
    ctx = AgentContext()
    ctx.abort_event.set()

    params = QueryParams(
        provider=provider,  # type: ignore[arg-type]
        system_prompt="x",
        tools=[],
        can_use_tool=always_allow,
        hooks=HookRegistry(),
        initial_messages=[],
    )
    events = [ev async for ev in query_loop(params, ctx)]
    terminals = [ev for ev in events if isinstance(ev, LoopTerminated)]
    assert terminals[0].transition.reason == "aborted"
    assert terminals[0].total_turns == 0
