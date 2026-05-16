"""Real-API integration:Coordinator(leader-worker)真實多 agent dispatch。

驗證:
- Coordinator 真實 spawn N 個 worker
- 每個 worker 都是獨立 Anthropic call(parallel)
- 所有 worker 完成後 reports 順序對齊 assignments
- 每個 worker 真的回了內容
"""

from __future__ import annotations

import os

import pytest

from orion_sdk.core.state import AgentContext
from orion_sdk.multi_agent.coordinator import Coordinator
from orion_sdk.multi_agent.types import TaskAssignment
from orion_sdk.services.feature_flags import load_feature_flags
from orion_sdk.services.forked_agent import CacheSafeParams
from orion_model.provider import get_provider

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)


@pytest.mark.asyncio
async def test_coordinator_dispatches_two_workers() -> None:
    """兩個獨立 worker 各自回 LLM 真實答案,reports 順序對齊。"""
    ctx = AgentContext(feature_flags=load_feature_flags())
    provider = get_provider("anthropic", "claude-haiku-4-5")  # 便宜 + 快

    cache_safe = CacheSafeParams.from_parts(
        system_prompt="You are concise. Answer in one short sentence.",
        tools=[],
        messages=[],
    )

    coord = Coordinator(
        ctx=ctx,
        provider=provider,
        cache_safe_params=cache_safe,
        max_workers=3,
    )

    assignments = [
        TaskAssignment(description="Output exactly: ALPHA-RESULT", max_turns=1),
        TaskAssignment(description="Output exactly: BETA-RESULT", max_turns=1),
    ]

    result = await coord.dispatch(assignments)

    assert len(result.reports) == 2
    # reports 順序對齊 assignments(by task_id)
    assert result.reports[0].task_id == assignments[0].task_id
    assert result.reports[1].task_id == assignments[1].task_id
    # 兩個 worker 都 completed
    assert all(r.status == "completed" for r in result.reports), (
        f"some workers failed: {[(r.status, r.error) for r in result.reports]}"
    )
    # 真實 LLM 輸出含預期 token
    combined_0 = result.reports[0].final_text.upper()
    combined_1 = result.reports[1].final_text.upper()
    assert "ALPHA-RESULT" in combined_0, f"worker 0 didn't echo: {combined_0!r}"
    assert "BETA-RESULT" in combined_1, f"worker 1 didn't echo: {combined_1!r}"
