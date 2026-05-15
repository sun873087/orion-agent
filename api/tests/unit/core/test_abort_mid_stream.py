"""Phase 16 — ctx.abort_event 中途 set 時,provider.stream() 不應跑完才停。

目標:
- SlowMockProvider 模擬一個會慢慢吐 chunk 的 stream
- 另一 task 在 stream 跑到一半時 set ctx.abort_event
- query_loop 應在數百毫秒內結束(不是等 SlowMockProvider 全跑完)
- transition.reason == "aborted"
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import anyio
import pytest

from orion_agent.core.query_loop import (
    LoopTerminated,
    QueryParams,
    query_loop,
)
from orion_agent.core.state import AgentContext
from orion_agent.hooks.registry import HookRegistry
from orion_model.events import (
    MessageStartEvent,
    MessageStopEvent,
    NormalizedEvent,
    NormalizedUsage,
    TextDeltaEvent,
)
from orion_model.provider import ProviderCapabilities
from orion_model.tool_def import ToolDefinition
from orion_model.types import NormalizedMessage
from orion_agent.permissions.decisions import always_allow


@dataclass
class SlowMockProvider:
    """每 chunk 之間 sleep delay_per_chunk 秒,模擬慢 stream。"""

    name: str = "slow-mock"
    model: str = "slow-1"
    delay_per_chunk: float = 0.5
    total_chunks: int = 20
    capabilities: ProviderCapabilities = field(
        default_factory=lambda: ProviderCapabilities(
            prompt_caching=False,
            auto_caching=False,
            parallel_tool_calls=True,
            native_mcp=False,
            structured_output=False,
            reasoning_blocks=False,
            max_context_tokens=200_000,
        )
    )

    async def stream(
        self,
        *,
        system: str | list[str],  # noqa: ARG002
        messages: list[NormalizedMessage],  # noqa: ARG002
        tools: list[ToolDefinition] | None = None,  # noqa: ARG002
        max_tokens: int = 4096,  # noqa: ARG002
        temperature: float | None = None,  # noqa: ARG002
        cache_breakpoints: list[int] | None = None,  # noqa: ARG002
        reasoning_effort: Any = None,  # noqa: ARG002
    ) -> AsyncIterator[NormalizedEvent]:
        yield MessageStartEvent(message_id="slow_msg", model=self.model)
        for i in range(self.total_chunks):
            await anyio.sleep(self.delay_per_chunk)
            yield TextDeltaEvent(text=f"chunk{i} ")
        yield MessageStopEvent(
            stop_reason="end_turn",
            usage=NormalizedUsage(input_tokens=0, output_tokens=0),
        )

    def estimate_cost(self, **_: Any) -> float:
        return 0.0


@pytest.mark.asyncio
async def test_abort_during_stream_terminates_immediately() -> None:
    """abort_event 在 stream 跑到一半 set → query_loop 應在 < 1 秒內結束。"""
    slow_provider = SlowMockProvider(delay_per_chunk=0.5, total_chunks=20)
    ctx = AgentContext()

    params = QueryParams(
        provider=slow_provider,  # type: ignore[arg-type]
        system_prompt="x",
        tools=[],
        can_use_tool=always_allow,
        hooks=HookRegistry(),
        initial_messages=[],
    )

    async def trigger_abort() -> None:
        await anyio.sleep(0.1)
        ctx.abort_event.set()

    start = time.monotonic()
    events: list[Any] = []
    async with anyio.create_task_group() as tg:
        tg.start_soon(trigger_abort)
        async for ev in query_loop(params, ctx):
            events.append(ev)
    elapsed = time.monotonic() - start

    # 該在 1 秒內結束(不是 10 秒等 stream 完)
    assert elapsed < 1.0, f"loop took {elapsed:.2f}s — expected < 1.0s"

    terminals = [ev for ev in events if isinstance(ev, LoopTerminated)]
    assert len(terminals) == 1
    assert terminals[0].transition.reason == "aborted"


@pytest.mark.asyncio
async def test_abort_after_stream_finished_normal() -> None:
    """abort 沒被 set,stream 自然跑完 → natural_stop,不影響正常路徑。"""
    fast_provider = SlowMockProvider(delay_per_chunk=0.01, total_chunks=3)
    ctx = AgentContext()

    params = QueryParams(
        provider=fast_provider,  # type: ignore[arg-type]
        system_prompt="x",
        tools=[],
        can_use_tool=always_allow,
        hooks=HookRegistry(),
        initial_messages=[],
    )

    events = [ev async for ev in query_loop(params, ctx)]
    terminals = [ev for ev in events if isinstance(ev, LoopTerminated)]
    assert terminals[0].transition.reason == "natural_stop"


@pytest.mark.asyncio
async def test_abort_aware_scope_no_false_positive() -> None:
    """body 正常完成時,cancel_called 應為 False(不被 finally cancel 污染)。"""
    from orion_agent.core.abort import abort_aware_scope

    event = anyio.Event()
    async with abort_aware_scope(event) as scope:
        await anyio.sleep(0.05)
    assert not scope.cancel_called


@pytest.mark.asyncio
async def test_abort_aware_scope_triggers_on_event_set() -> None:
    """abort_event 在 body 跑到一半 set → scope.cancel_called True。"""
    from orion_agent.core.abort import abort_aware_scope

    event = anyio.Event()

    async def setter() -> None:
        await anyio.sleep(0.05)
        event.set()

    async with abort_aware_scope(event, poll_interval=0.01) as scope:
        async with anyio.create_task_group() as tg:
            tg.start_soon(setter)
            await anyio.sleep(5.0)  # 會被 cancel
    assert scope.cancel_called
