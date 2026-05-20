"""Tests for orion_sdk.memory.quota (Layer 4)。"""

from __future__ import annotations

from pathlib import Path

import pytest

from orion_sdk.memory.quota import (
    count_by_type,
    memories_of_type,
    over_quota_types,
    quota_for,
)
from orion_sdk.memory.types import Memory, MemoryFrontmatter, MemoryType


def _make_memory(name: str, mtype: MemoryType | None) -> Memory:
    fm = MemoryFrontmatter(name=name, description=f"d-{name}", type=mtype)
    return Memory(frontmatter=fm, body="body", file_path=Path(f"{name}.md"))


def test_quota_for_returns_defaults() -> None:
    assert quota_for(MemoryType.USER) == 50
    assert quota_for(MemoryType.FEEDBACK) == 100
    assert quota_for(MemoryType.PROJECT) == 30
    assert quota_for(MemoryType.REFERENCE) == 50
    assert quota_for(None) == 50


def test_quota_for_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORION_MEMORY_QUOTA_FEEDBACK", "200")
    assert quota_for(MemoryType.FEEDBACK) == 200


def test_quota_for_bad_env_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORION_MEMORY_QUOTA_USER", "not-a-number")
    assert quota_for(MemoryType.USER) == 50
    monkeypatch.setenv("ORION_MEMORY_QUOTA_USER", "-5")
    assert quota_for(MemoryType.USER) == 50


def test_count_by_type() -> None:
    mems = [
        _make_memory("a", MemoryType.USER),
        _make_memory("b", MemoryType.USER),
        _make_memory("c", MemoryType.FEEDBACK),
        _make_memory("d", None),
    ]
    counts = count_by_type(mems)
    assert counts[MemoryType.USER] == 2
    assert counts[MemoryType.FEEDBACK] == 1
    assert counts[None] == 1


def test_over_quota_types(monkeypatch: pytest.MonkeyPatch) -> None:
    # 把 FEEDBACK quota 降到 2,USER 不動
    monkeypatch.setenv("ORION_MEMORY_QUOTA_FEEDBACK", "2")
    mems = [
        _make_memory("a", MemoryType.USER),
        _make_memory("b", MemoryType.FEEDBACK),
        _make_memory("c", MemoryType.FEEDBACK),
        _make_memory("d", MemoryType.FEEDBACK), # 3 > quota 2
    ]
    over = over_quota_types(mems)
    assert len(over) == 1
    assert over[0] == (MemoryType.FEEDBACK, 3, 2)


def test_memories_of_type() -> None:
    mems = [
        _make_memory("a", MemoryType.USER),
        _make_memory("b", MemoryType.FEEDBACK),
        _make_memory("c", MemoryType.USER),
        _make_memory("d", None),
    ]
    user_mems = memories_of_type(mems, MemoryType.USER)
    assert {m.name for m in user_mems} == {"a", "c"}

    none_mems = memories_of_type(mems, None)
    assert [m.name for m in none_mems] == ["d"]
