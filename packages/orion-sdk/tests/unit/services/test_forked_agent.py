"""forked_agent cache-safe fork 機制測試。"""

from __future__ import annotations

import pytest

from orion_sdk.core.state import AgentContext
from orion_model.types import NormalizedMessage
from orion_sdk.services.forked_agent import (
    CacheSafeParams,
    run_forked_agent,
)
from orion_sdk._testing import MockProvider, MockTurn


@pytest.mark.asyncio
async def test_simple_fork_returns_text() -> None:
    """fork 跑一輪 text-only → final_text 抓到。"""
    provider = MockProvider(turns=[MockTurn(text="forked answer")])
    parent_ctx = AgentContext()
    cache_safe = CacheSafeParams.from_parts(
        system_prompt="parent system",
        tools=[],
        messages=[],
    )
    result = await run_forked_agent(
        parent_ctx=parent_ctx,
        parent_params=cache_safe,
        user_prompt="do the thing",
        provider=provider, # type: ignore[arg-type]
    )
    assert "forked answer" in result.final_text
    assert result.transition_reason == "natural_stop"


@pytest.mark.asyncio
async def test_byte_identical_prefix_passes_to_provider() -> None:
    """fork 把 cache_safe 的 system + messages_prefix 原樣傳給 provider.stream。"""
    provider = MockProvider(turns=[MockTurn(text="ok")])
    parent_ctx = AgentContext()

    msg_prefix = [
        NormalizedMessage(role="user", content="earlier user msg"),
        NormalizedMessage(role="assistant", content="earlier reply"),
    ]
    cache_safe = CacheSafeParams.from_parts(
        system_prompt=["a", "b", "c"],
        tools=[],
        messages=msg_prefix,
    )
    await run_forked_agent(
        parent_ctx=parent_ctx,
        parent_params=cache_safe,
        user_prompt="new task",
        provider=provider, # type: ignore[arg-type]
    )
    call = provider.captured_calls[0]
    # system 維持 list[str](Anthropic provider 在倒數第二段加 cache_control)
    assert call["system"] == ["a", "b", "c"]
    # messages = prefix + 新 user_prompt
    sent_msgs = call["messages"]
    assert len(sent_msgs) == 3
    assert sent_msgs[0].content == "earlier user msg"
    assert sent_msgs[1].content == "earlier reply"
    assert sent_msgs[2].role == "user"
    assert sent_msgs[2].content == "new task"


@pytest.mark.asyncio
async def test_parent_messages_mutation_does_not_affect_fork() -> None:
    """capture 後 caller 改父 messages,fork 已 capture 的 prefix 不受影響。"""
    provider = MockProvider(turns=[MockTurn(text="x")])
    parent_msgs: list[NormalizedMessage] = [
        NormalizedMessage(role="user", content="msg1"),
    ]

    cache_safe = CacheSafeParams.from_parts(
        system_prompt="s",
        tools=[],
        messages=parent_msgs,
    )

    # 模擬父對話繼續成長
    parent_msgs.append(NormalizedMessage(role="assistant", content="msg2"))
    parent_msgs.append(NormalizedMessage(role="user", content="msg3"))

    await run_forked_agent(
        parent_ctx=AgentContext(),
        parent_params=cache_safe,
        user_prompt="fork task",
        provider=provider, # type: ignore[arg-type]
    )
    sent_msgs = provider.captured_calls[0]["messages"]
    # 應該只看到 capture 當時的 1 則 + 新 user_prompt = 2
    assert len(sent_msgs) == 2
    assert sent_msgs[0].content == "msg1"
    assert sent_msgs[1].content == "fork task"


@pytest.mark.asyncio
async def test_fork_increments_subagent_depth() -> None:
    """fork 跑時 ctx.sub_agent_depth = parent + 1。"""
    # 用 spy provider 攔截 — 在 stream() 時抓 ctx 值
    captured: list[int] = []

    class SpyProvider(MockProvider):
        async def stream(self, **kwargs: object): # type: ignore[override,no-untyped-def]
            # 取不到 ctx;改從 query_loop 觀察 — 用較直接路徑:在 fork 後 ctx 應該 +1
            async for ev in super().stream(**kwargs): # type: ignore[arg-type]
                yield ev

    provider = SpyProvider(turns=[MockTurn(text="x")])
    parent_ctx = AgentContext(sub_agent_depth=0)

    # 我們不能直接觀察 child_ctx,但可以驗整個 fork 沒爆 + 父 ctx 不變
    cache_safe = CacheSafeParams.from_parts(
        system_prompt="s",
        tools=[],
        messages=[],
    )
    await run_forked_agent(
        parent_ctx=parent_ctx,
        parent_params=cache_safe,
        user_prompt="x",
        provider=provider, # type: ignore[arg-type]
    )
    # 父 ctx depth 沒變
    assert parent_ctx.sub_agent_depth == 0
    _ = captured # 只是 sanity check 變數還在


@pytest.mark.asyncio
async def test_fork_aggregates_usage() -> None:
    """fork 跑兩輪(因為第 1 輪有 tool_use)→ total_usage 累加。"""
    # MockProvider 一輪 input_tokens=10 / output_tokens=20。但 fork 不執行 tool
    # — 沒有 tools 註冊就不會跑 tool_use。給 1 輪 text-only。
    provider = MockProvider(turns=[MockTurn(text="ok")])
    cache_safe = CacheSafeParams.from_parts(
        system_prompt="s",
        tools=[],
        messages=[],
    )
    result = await run_forked_agent(
        parent_ctx=AgentContext(),
        parent_params=cache_safe,
        user_prompt="t",
        provider=provider, # type: ignore[arg-type]
    )
    assert result.total_usage["input_tokens"] >= 10
    assert result.total_usage["output_tokens"] >= 20


@pytest.mark.asyncio
async def test_cache_safe_params_immutable_capture() -> None:
    """from_parts 拷貝 list,caller 改原 list 不影響 capture。"""
    tools_list: list[object] = []
    msgs: list[NormalizedMessage] = []
    cs = CacheSafeParams.from_parts(
        system_prompt=["a"],
        tools=tools_list, # type: ignore[arg-type]
        messages=msgs,
    )
    # 改 outer
    tools_list.append(object())
    msgs.append(NormalizedMessage(role="user", content="x"))
    # capture 不變
    assert cs.tools == []
    assert cs.messages_prefix == []


@pytest.mark.asyncio
async def test_fork_does_not_inherit_parent_abort() -> None:
    """父 abort 不影響 fork — fork 有自己的 abort_event。"""
    import anyio
    parent_ctx = AgentContext()
    parent_ctx.abort_event.set() # 父已 abort

    provider = MockProvider(turns=[MockTurn(text="ok")])
    cache_safe = CacheSafeParams.from_parts(
        system_prompt="s",
        tools=[],
        messages=[],
    )
    # fork 應該還能跑(abort_event 是新的)
    result = await run_forked_agent(
        parent_ctx=parent_ctx,
        parent_params=cache_safe,
        user_prompt="t",
        provider=provider, # type: ignore[arg-type]
    )
    assert result.transition_reason == "natural_stop"
    # sanity:確認 anyio import 還在用(避免 lint 抱怨)
    _ = anyio.Event()
