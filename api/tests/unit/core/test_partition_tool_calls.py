"""partition_tool_calls — 連續 safe 打 batch、non-safe 自成 batch。"""

from __future__ import annotations

from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from orion_agent.core.tool_orchestration import partition_tool_calls
from orion_model.types import ToolUseBlock


class _SafeTool:
    name = "Safe"
    description = "x"

    class Input:
        @classmethod
        def model_validate(cls, _v: dict[str, Any]) -> _SafeTool.Input:
            return cls()

    input_schema = Input

    def is_concurrency_safe(self, _: Any) -> bool:
        return True


class _UnsafeTool:
    name = "Unsafe"
    description = "x"

    class Input:
        @classmethod
        def model_validate(cls, _v: dict[str, Any]) -> _UnsafeTool.Input:
            return cls()

    input_schema = Input

    def is_concurrency_safe(self, _: Any) -> bool:
        return False


def _block(name: str, idx: int) -> ToolUseBlock:
    return ToolUseBlock(id=f"id_{idx}", name=name, input={})


def test_empty() -> None:
    assert partition_tool_calls([], []) == []


def test_all_safe_one_batch() -> None:
    tools = [_SafeTool()]
    blocks = [_block("Safe", i) for i in range(5)]
    batches = partition_tool_calls(blocks, tools)  # type: ignore[arg-type]
    assert len(batches) == 1
    assert batches[0].is_concurrency_safe is True
    assert len(batches[0].blocks) == 5


def test_all_unsafe_each_own_batch() -> None:
    tools = [_UnsafeTool()]
    blocks = [_block("Unsafe", i) for i in range(3)]
    batches = partition_tool_calls(blocks, tools)  # type: ignore[arg-type]
    assert len(batches) == 3
    assert all(not b.is_concurrency_safe for b in batches)


def test_safe_unsafe_safe_three_batches() -> None:
    tools = [_SafeTool(), _UnsafeTool()]
    blocks = [_block("Safe", 1), _block("Unsafe", 2), _block("Safe", 3)]
    batches = partition_tool_calls(blocks, tools)  # type: ignore[arg-type]
    assert len(batches) == 3
    assert batches[0].is_concurrency_safe
    assert not batches[1].is_concurrency_safe
    assert batches[2].is_concurrency_safe


def test_unknown_tool_treated_as_unsafe() -> None:
    tools = [_SafeTool()]
    blocks = [_block("Safe", 1), _block("MissingTool", 2), _block("Safe", 3)]
    batches = partition_tool_calls(blocks, tools)  # type: ignore[arg-type]
    assert len(batches) == 3  # safe / non-safe (missing) / safe
    assert not batches[1].is_concurrency_safe


@given(
    st.lists(
        st.tuples(
            st.sampled_from(["Safe", "Unsafe"]),
            st.integers(min_value=0, max_value=1000),
        ),
        max_size=20,
    )
)
def test_partition_invariants(seq: list[tuple[str, int]]) -> None:
    """hypothesis:任何序列下,batch invariant 成立。"""
    tools = [_SafeTool(), _UnsafeTool()]
    blocks = [_block(n, i) for i, (n, _) in enumerate(seq)]
    batches = partition_tool_calls(blocks, tools)  # type: ignore[arg-type]

    # 1. 總 block 數守恒
    total = sum(len(b.blocks) for b in batches)
    assert total == len(seq)

    # 2. is_concurrency_safe=False 的 batch 必然只有一個 block
    for b in batches:
        if not b.is_concurrency_safe:
            assert len(b.blocks) == 1

    # 3. 同一 batch 內所有 block 的 safety 一致
    for b in batches:
        if b.is_concurrency_safe:
            for bl in b.blocks:
                assert bl.name == "Safe"

    # 4. 相鄰兩 batch 不會兩個都是 safe(否則應 merge)
    for i in range(len(batches) - 1):
        assert not (batches[i].is_concurrency_safe and batches[i + 1].is_concurrency_safe)
