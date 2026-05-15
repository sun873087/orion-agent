"""compact/tombstone.py。"""

from __future__ import annotations

import pytest

from orion_sdk.compact.tombstone import replace_range_with_tombstone
from orion_model.types import NormalizedMessage, TombstoneBlock


def _msg(role: str, content: str) -> NormalizedMessage:
    return NormalizedMessage(role=role, content=content)  # type: ignore[arg-type]


def test_replace_range_basic() -> None:
    msgs = [_msg("user", "1"), _msg("assistant", "2"), _msg("user", "3"), _msg("assistant", "4")]
    out = replace_range_with_tombstone(
        msgs, start=0, end=1, summary="summary of first two", original_token_count=100,
    )
    assert len(out) == 3
    # 第一則應是 user with TombstoneBlock
    assert out[0].role == "user"
    assert isinstance(out[0].content, list)
    assert isinstance(out[0].content[0], TombstoneBlock)
    assert out[0].content[0].summary == "summary of first two"
    assert out[0].content[0].range_start_msg_index == 0
    assert out[0].content[0].range_end_msg_index == 1
    # 後面保留
    assert out[1].content == "3"
    assert out[2].content == "4"


def test_replace_range_invalid_raises() -> None:
    msgs = [_msg("user", "x")]
    with pytest.raises(ValueError):
        replace_range_with_tombstone(
            msgs, start=0, end=5, summary="x", original_token_count=0,
        )
    with pytest.raises(ValueError):
        replace_range_with_tombstone(
            msgs, start=2, end=1, summary="x", original_token_count=0,
        )


def test_pure_function_does_not_mutate() -> None:
    msgs = [_msg("user", "1"), _msg("user", "2")]
    out = replace_range_with_tombstone(
        msgs, start=0, end=0, summary="x", original_token_count=10,
    )
    assert msgs[0].content == "1"  # 原資料不動
    assert out is not msgs
