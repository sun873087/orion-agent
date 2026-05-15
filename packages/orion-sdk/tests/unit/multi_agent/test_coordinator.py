"""Coordinator — Phase 15。"""

from __future__ import annotations

import pytest

from orion_sdk.core.state import AgentContext
from orion_sdk.multi_agent.coordinator import Coordinator
from orion_sdk.multi_agent.types import TaskAssignment
from orion_sdk.services.forked_agent import CacheSafeParams
from orion_sdk._testing import MockProvider, MockTurn


def _cs() -> CacheSafeParams:
    return CacheSafeParams.from_parts(
        system_prompt="you are helpful",
        tools=[],
        messages=[],
    )


@pytest.mark.asyncio
async def test_dispatch_three_workers_parallel() -> None:
    """3 workers 各跑一輪 text-only,reports 與 assignments 對齊。"""
    provider = MockProvider(turns=[
        MockTurn(text="result A"),
        MockTurn(text="result B"),
        MockTurn(text="result C"),
    ])
    coord = Coordinator(
        ctx=AgentContext(),
        provider=provider,  # type: ignore[arg-type]
        cache_safe_params=_cs(),
    )
    a1 = TaskAssignment(description="task A")
    a2 = TaskAssignment(description="task B")
    a3 = TaskAssignment(description="task C")
    result = await coord.dispatch([a1, a2, a3])

    # 全 completed
    assert all(r.status == "completed" for r in result.reports)
    # 順序與 assignments 對齊
    assert [r.task_id for r in result.reports] == [a1.task_id, a2.task_id, a3.task_id]
    # final_text 各自包含 result text(MockProvider 共用 turns,可能順序非定;但全部
    # 必含 result 字)
    texts = [r.final_text for r in result.reports]
    assert all("result" in t for t in texts)


@pytest.mark.asyncio
async def test_dispatch_empty_returns_empty() -> None:
    coord = Coordinator(
        ctx=AgentContext(),
        provider=MockProvider(),  # type: ignore[arg-type]
        cache_safe_params=_cs(),
    )
    result = await coord.dispatch([])
    assert result.reports == []


@pytest.mark.asyncio
async def test_dispatch_too_many_raises() -> None:
    coord = Coordinator(
        ctx=AgentContext(),
        provider=MockProvider(),  # type: ignore[arg-type]
        cache_safe_params=_cs(),
        max_workers=2,
    )
    with pytest.raises(ValueError, match="Too many"):
        await coord.dispatch([
            TaskAssignment(description="x"),
            TaskAssignment(description="y"),
            TaskAssignment(description="z"),
        ])


@pytest.mark.asyncio
async def test_worker_failure_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    """個別 worker 失敗不影響其他;失敗 worker 回 status=failed。"""
    provider = MockProvider(turns=[
        MockTurn(text="ok 1"),
        MockTurn(text="ok 2"),
    ])

    real_run = None
    call_count = {"n": 0}

    async def fake_run_forked_agent(**kwargs):  # type: ignore[no-untyped-def]
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("worker exploded")
        from orion_sdk.services.forked_agent import (
            run_forked_agent as orig,
        )
        return await orig(**kwargs)

    monkeypatch.setattr(
        "orion_sdk.multi_agent.coordinator.run_forked_agent",
        fake_run_forked_agent,
    )

    coord = Coordinator(
        ctx=AgentContext(),
        provider=provider,  # type: ignore[arg-type]
        cache_safe_params=_cs(),
    )
    a1 = TaskAssignment(description="A")
    a2 = TaskAssignment(description="B-explode")
    a3 = TaskAssignment(description="C")
    result = await coord.dispatch([a1, a2, a3])

    # 有 1 個 failed,其他 2 個 completed
    assert len(result.failed) == 1
    assert len(result.succeeded) == 2
    failed = result.failed[0]
    assert "RuntimeError" in (failed.error or "")
    assert "worker exploded" in (failed.error or "")
    # sanity: real_run 還是有效路徑(assert 用一下)
    _ = real_run


@pytest.mark.asyncio
async def test_dispatch_aggregates_usage() -> None:
    """total_usage 加總所有 worker。"""
    provider = MockProvider(turns=[
        MockTurn(text="x"),
        MockTurn(text="y"),
    ])
    coord = Coordinator(
        ctx=AgentContext(),
        provider=provider,  # type: ignore[arg-type]
        cache_safe_params=_cs(),
    )
    result = await coord.dispatch([
        TaskAssignment(description="a"),
        TaskAssignment(description="b"),
    ])
    # MockProvider 每 turn 給 input=10 / output=20 → 2 worker × 1 turn 各
    assert result.total_usage["input_tokens"] >= 20
    assert result.total_usage["output_tokens"] >= 40


@pytest.mark.asyncio
async def test_summary_provider_optional() -> None:
    """summary_provider=None → reports.summary 維持空字串(不嘗試 summarize)。"""
    provider = MockProvider(turns=[MockTurn(text="done")])
    coord = Coordinator(
        ctx=AgentContext(),
        provider=provider,  # type: ignore[arg-type]
        cache_safe_params=_cs(),
        summary_provider=None,
    )
    result = await coord.dispatch([TaskAssignment(description="a")])
    assert result.reports[0].summary == ""


@pytest.mark.asyncio
async def test_summary_provider_invoked() -> None:
    """summary_provider 給了 → reports.summary 取自 generate_agent_summary。"""
    main_provider = MockProvider(turns=[MockTurn(text="working...")])
    summary_provider = MockProvider(turns=[
        MockTurn(text="Worker did the thing successfully."),
    ])
    coord = Coordinator(
        ctx=AgentContext(),
        provider=main_provider,  # type: ignore[arg-type]
        cache_safe_params=_cs(),
        summary_provider=summary_provider,  # type: ignore[arg-type]
    )
    result = await coord.dispatch([TaskAssignment(description="x")])
    assert "Worker did" in result.reports[0].summary
