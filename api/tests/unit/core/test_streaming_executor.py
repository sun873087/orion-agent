"""StreamingToolExecutor — add_tool / can_execute_tool / drain。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import anyio
import pytest

from orion_agent.core.state import AgentContext
from orion_agent.core.streaming_executor import StreamingToolExecutor
from orion_agent.core.tool import TextEvent, ToolEvent, ToolInput
from orion_agent.core.tool_execution import ToolResultUpdate
from orion_agent.hooks.registry import HookRegistry
from orion_model.types import ToolUseBlock
from orion_agent.permissions.decisions import always_allow


class _SafeInput(ToolInput):
    delay: float = 0.05


class _SafeTool:
    name = "Safe"
    description = "x"
    input_schema = _SafeInput

    async def call(
        self, input: _SafeInput, ctx: AgentContext  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        await anyio.sleep(input.delay)
        yield TextEvent(text=f"safe-{input.delay}")

    def is_concurrency_safe(self, _: _SafeInput) -> bool:
        return True

    def is_read_only(self, _: _SafeInput) -> bool:
        return True

    def max_result_size_chars(self) -> int | float:
        return 1000


class _UnsafeInput(ToolInput):
    label: str


class _UnsafeTool:
    name = "Unsafe"
    description = "x"
    input_schema = _UnsafeInput

    async def call(
        self, input: _UnsafeInput, ctx: AgentContext  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        await anyio.sleep(0.01)
        yield TextEvent(text=f"unsafe-{input.label}")

    def is_concurrency_safe(self, _: _UnsafeInput) -> bool:
        return False

    def is_read_only(self, _: _UnsafeInput) -> bool:
        return False

    def max_result_size_chars(self) -> int | float:
        return 1000


@pytest.mark.asyncio
async def test_drain_yields_in_add_order() -> None:
    """add A(slow) → B(fast) → C(medium),drain 出來順序 A, B, C。"""
    async with StreamingToolExecutor(
        [_SafeTool()],  # type: ignore[list-item]
        can_use_tool=always_allow,
        hooks=HookRegistry(),
        ctx=AgentContext(),
    ) as exe:
        exe.add_tool(ToolUseBlock(id="A", name="Safe", input={"delay": 0.2}))
        exe.add_tool(ToolUseBlock(id="B", name="Safe", input={"delay": 0.05}))
        exe.add_tool(ToolUseBlock(id="C", name="Safe", input={"delay": 0.1}))

        results: list[str] = []
        async for upd in exe.drain():
            if isinstance(upd, ToolResultUpdate):
                results.append(upd.tool_use_id)
        assert results == ["A", "B", "C"]


@pytest.mark.asyncio
async def test_unsafe_blocks_subsequent() -> None:
    """add Safe → Unsafe → Safe:Unsafe 須等第一個 Safe 完才開,後面的 Safe 須等
    Unsafe 完才開。"""
    async with StreamingToolExecutor(
        [_SafeTool(), _UnsafeTool()],  # type: ignore[list-item]
        can_use_tool=always_allow,
        hooks=HookRegistry(),
        ctx=AgentContext(),
    ) as exe:
        exe.add_tool(ToolUseBlock(id="s1", name="Safe", input={"delay": 0.05}))
        exe.add_tool(ToolUseBlock(id="u1", name="Unsafe", input={"label": "x"}))
        exe.add_tool(ToolUseBlock(id="s2", name="Safe", input={"delay": 0.05}))

        order: list[str] = []
        async for upd in exe.drain():
            if isinstance(upd, ToolResultUpdate):
                order.append(upd.tool_use_id)
        assert order == ["s1", "u1", "s2"]


@pytest.mark.asyncio
async def test_unknown_tool_yields_synthetic_error() -> None:
    """送一個沒註冊的 tool name → 一樣有 ToolResultUpdate(is_error=True)。"""
    async with StreamingToolExecutor(
        [_SafeTool()],  # type: ignore[list-item]
        can_use_tool=always_allow,
        hooks=HookRegistry(),
        ctx=AgentContext(),
    ) as exe:
        exe.add_tool(ToolUseBlock(id="x", name="DoesNotExist", input={}))

        results = [u async for u in exe.drain() if isinstance(u, ToolResultUpdate)]
        assert len(results) == 1
        assert results[0].is_error is True


class _ErroringUnsafeInput(ToolInput):
    msg: str = "boom"


class _ErroringUnsafeTool:
    """non-safe 工具,執行就 yield ErrorEvent → 觸發 sibling abort。"""

    name = "BadUnsafe"
    description = "x"
    input_schema = _ErroringUnsafeInput

    async def call(
        self, input: _ErroringUnsafeInput, ctx: AgentContext  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        from orion_agent.core.tool import ErrorEvent
        yield ErrorEvent(message=input.msg)

    def is_concurrency_safe(self, _: _ErroringUnsafeInput) -> bool:
        return False  # 關鍵:non-safe 才會觸發 sibling abort

    def is_read_only(self, _: _ErroringUnsafeInput) -> bool:
        return False

    def max_result_size_chars(self) -> int | float:
        return 1000


@pytest.mark.asyncio
async def test_sibling_abort_skips_queued_after_unsafe_error() -> None:
    """non-safe 工具出錯 → set sibling_abort → queued 工具 skip 不執行。"""
    async with StreamingToolExecutor(
        [_ErroringUnsafeTool(), _SafeTool()],  # type: ignore[list-item]
        can_use_tool=always_allow,
        hooks=HookRegistry(),
        ctx=AgentContext(),
    ) as exe:
        exe.add_tool(ToolUseBlock(id="bad", name="BadUnsafe", input={"msg": "kaboom"}))
        exe.add_tool(ToolUseBlock(id="s1", name="Safe", input={"delay": 0.05}))
        exe.add_tool(ToolUseBlock(id="s2", name="Safe", input={"delay": 0.05}))

        results = [u async for u in exe.drain() if isinstance(u, ToolResultUpdate)]
        assert len(results) == 3
        ids = [r.tool_use_id for r in results]
        assert ids == ["bad", "s1", "s2"]
        # 第一個錯誤(bad),後面兩個 sibling 應 skip
        assert results[0].is_error is True
        assert results[1].is_error is True
        assert results[2].is_error is True
        for r in results[1:]:
            assert "sibling" in str(r.message.content).lower()


@pytest.mark.asyncio
async def test_sibling_abort_event_set_after_unsafe_error() -> None:
    """sibling_abort.is_set() 在 non-safe 工具 ErrorEvent 後應為 True。"""
    async with StreamingToolExecutor(
        [_ErroringUnsafeTool()],  # type: ignore[list-item]
        can_use_tool=always_allow,
        hooks=HookRegistry(),
        ctx=AgentContext(),
    ) as exe:
        exe.add_tool(ToolUseBlock(id="bad", name="BadUnsafe", input={}))
        _ = [u async for u in exe.drain()]
        assert exe.sibling_abort.is_set() is True


@pytest.mark.asyncio
async def test_safe_error_does_not_trigger_sibling_abort() -> None:
    """concurrency-safe 工具出錯 不觸發 sibling abort(只影響自己)。"""
    async with StreamingToolExecutor(
        [_SafeTool()],  # type: ignore[list-item]
        can_use_tool=always_allow,
        hooks=HookRegistry(),
        ctx=AgentContext(),
    ) as exe:
        exe.add_tool(ToolUseBlock(id="x", name="DoesNotExist", input={}))  # synthetic err
        exe.add_tool(ToolUseBlock(id="ok", name="Safe", input={"delay": 0.01}))
        results = [u async for u in exe.drain() if isinstance(u, ToolResultUpdate)]
        # x 失敗,ok 仍然 succeed(safe 錯不擋)
        assert results[0].is_error is True
        assert results[1].is_error is False
        assert exe.sibling_abort.is_set() is False
