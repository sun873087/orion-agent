"""storage/replacement_state.py — 第 3 層 budget 三類分流。"""

from __future__ import annotations

from uuid import uuid4

from orion_agent.llm.types import NormalizedMessage, ToolResultBlock, ToolUseBlock
from orion_agent.storage.replacement_state import (
    ContentReplacementState,
    ToolResultCandidate,
    apply_tool_result_budget,
    collect_candidates,
    partition_by_prior_decision,
    select_fresh_to_replace,
)


def _candidate(id_: str, size: int) -> ToolResultCandidate:
    return ToolResultCandidate(tool_use_id=id_, size=size, content="x" * size)


def test_partition_three_categories() -> None:
    state = ContentReplacementState(
        seen_ids={"a", "b", "c"},
        replacements={"a": "preview-a"},
    )
    candidates = [_candidate("a", 100), _candidate("b", 200), _candidate("c", 300), _candidate("d", 400)]
    p = partition_by_prior_decision(candidates, state)
    assert [c.tool_use_id for c in p.must_reapply] == ["a"]
    assert sorted(c.tool_use_id for c in p.frozen) == ["b", "c"]
    assert [c.tool_use_id for c in p.fresh] == ["d"]


def test_select_fresh_under_budget_returns_empty() -> None:
    fresh = [_candidate("a", 100), _candidate("b", 200)]
    sel = select_fresh_to_replace(fresh, frozen_size=0, must_reapply_size=0, limit=1000)
    assert sel == []


def test_select_fresh_picks_largest_first() -> None:
    fresh = [_candidate("a", 100), _candidate("b", 500), _candidate("c", 200)]
    # total fresh = 800,limit = 300 → 需替換最少數量直到 fresh_remaining + 0 <= 300
    # 挑 b(500)→ remaining 300 <= 300,停。
    sel = select_fresh_to_replace(fresh, frozen_size=0, must_reapply_size=0, limit=300)
    assert [c.tool_use_id for c in sel] == ["b"]


def test_select_fresh_multiple_picks() -> None:
    fresh = [_candidate("a", 100), _candidate("b", 500), _candidate("c", 200)]
    # limit = 100 → 挑 b(500)後 remaining = 300 > 100,挑 c(200)後 remaining = 100,OK
    sel = select_fresh_to_replace(fresh, frozen_size=0, must_reapply_size=0, limit=100)
    assert [c.tool_use_id for c in sel] == ["b", "c"]


def test_apply_budget_no_overflow_unchanged() -> None:
    sid = uuid4()
    state = ContentReplacementState()
    msgs = [
        NormalizedMessage(
            role="user",
            content=[ToolResultBlock(tool_use_id="t1", content="small")],
        )
    ]
    new_msgs, decisions = apply_tool_result_budget(msgs, state, sid, limit=10_000)
    assert decisions == []
    assert "t1" in state.seen_ids
    # 沒替換 → frozen
    assert state.is_frozen("t1")


def test_apply_budget_replaces_largest_then_freezes_decision() -> None:
    sid = uuid4()
    state = ContentReplacementState()
    big = "x" * 200_000
    msgs = [
        NormalizedMessage(
            role="user",
            content=[
                ToolResultBlock(tool_use_id="t1", content="small"),
                ToolResultBlock(tool_use_id="t2", content=big),
            ],
        )
    ]
    new_msgs, decisions = apply_tool_result_budget(msgs, state, sid, limit=10_000)
    assert len(decisions) == 1
    assert decisions[0].tool_use_id == "t2"
    # state 紀錄 t2 是 must_reapply,t1 是 frozen
    assert state.is_must_reapply("t2")
    assert state.is_frozen("t1")
    # 第二次 apply(再傳同 messages)應 byte-identical 套用
    new_msgs2, decisions2 = apply_tool_result_budget(msgs, state, sid, limit=10_000)
    assert decisions2 == []
    # new_msgs / new_msgs2 內 t2 的 content 都是 envelope
    block = new_msgs[0].content[1]
    assert isinstance(block, ToolResultBlock)
    assert "<persisted-output" in str(block.content)


def test_collect_candidates_extracts_tool_results() -> None:
    msgs = [
        NormalizedMessage(role="user", content="hello"),
        NormalizedMessage(
            role="user",
            content=[
                ToolResultBlock(tool_use_id="t1", content="a"),
                ToolResultBlock(tool_use_id="t2", content="bb"),
            ],
        ),
        NormalizedMessage(
            role="assistant",
            content=[ToolUseBlock(id="t3", name="X", input={})],  # 不是 tool_result
        ),
    ]
    cands = collect_candidates(msgs)
    assert {c.tool_use_id for c in cands} == {"t1", "t2"}
