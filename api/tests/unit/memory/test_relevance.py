"""memory/relevance.py — heuristic + LLM modes。"""

from __future__ import annotations

from pathlib import Path

import pytest

from orion_agent.llm.types import NormalizedMessage
from orion_agent.memory.relevance import rank_memories
from orion_agent.memory.types import Memory, MemoryFrontmatter, MemoryType


def _mk(name: str, desc: str, body: str = "", t: MemoryType | None = MemoryType.USER) -> Memory:
    return Memory(
        frontmatter=MemoryFrontmatter(name=name, description=desc, type=t),
        body=body,
        file_path=Path(f"/tmp/{name}.md"),
    )


@pytest.mark.asyncio
async def test_empty_memories_returns_empty() -> None:
    msgs = [NormalizedMessage(role="user", content="hi")]
    out = await rank_memories([], msgs)
    assert out == []


@pytest.mark.asyncio
async def test_heuristic_keyword_match() -> None:
    """Default heuristic 模式:keyword 重疊高的優先。"""
    memories = [
        _mk("Python tips", "tricks for python development", "uses asyncio"),
        _mk("Lunch preference", "user likes ramen", "ramen"),
        _mk("Project deadline", "ship Q3", "deadline"),
    ]
    msgs = [NormalizedMessage(role="user", content="help me with python asyncio")]
    out = await rank_memories(memories, msgs, max_results=2)
    assert len(out) >= 1
    # Python 相關 memory 應在最前
    assert out[0].name == "Python tips"


@pytest.mark.asyncio
async def test_heuristic_no_match_falls_back_to_user_priority() -> None:
    """無 keyword 命中時回 user/feedback 類優先。"""
    memories = [
        _mk("Reference doc", "Linear URL", t=MemoryType.REFERENCE),
        _mk("Project info", "deadline X", t=MemoryType.PROJECT),
        _mk("User profile", "name is alice", t=MemoryType.USER),
        _mk("Feedback rule", "always test", t=MemoryType.FEEDBACK),
    ]
    msgs = [NormalizedMessage(role="user", content="completely_unrelated_query_xyz")]
    out = await rank_memories(memories, msgs, max_results=4)
    # user 應在 feedback 前
    types = [m.type for m in out]
    assert types[0] == MemoryType.USER
    assert types[1] == MemoryType.FEEDBACK


@pytest.mark.asyncio
async def test_max_results_limits_output() -> None:
    memories = [_mk(f"m{i}", "general") for i in range(20)]
    msgs = [NormalizedMessage(role="user", content="test")]
    out = await rank_memories(memories, msgs, max_results=3)
    assert len(out) == 3


@pytest.mark.asyncio
async def test_no_user_query_returns_priority_default() -> None:
    """No user message → return type-priority sorted memories。"""
    memories = [
        _mk("a", "x", t=MemoryType.PROJECT),
        _mk("b", "y", t=MemoryType.USER),
    ]
    msgs: list[NormalizedMessage] = []
    out = await rank_memories(memories, msgs, max_results=2)
    # USER 優先(priority=0 < project=2)
    assert out[0].type == MemoryType.USER
