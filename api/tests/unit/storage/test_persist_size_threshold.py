"""storage/tool_result.py — 第 2 層持久化邏輯。"""

from __future__ import annotations

from uuid import uuid4

from orion_agent.storage.tool_result import (
    LARGE_THRESHOLD_BYTES,
    PREVIEW_MAX_CHARS,
    generate_preview,
    maybe_persist_large_tool_result,
)


def test_small_content_not_persisted() -> None:
    sid = uuid4()
    r = maybe_persist_large_tool_result(sid, "tu1", "small text")
    assert r.persisted_path is None
    assert r.content_for_model == "small text"


def test_empty_content_replaced() -> None:
    sid = uuid4()
    r = maybe_persist_large_tool_result(sid, "tu1", "")
    assert r.persisted_path is None
    assert "no output" in r.content_for_model.lower()


def test_large_content_persisted_and_envelope_returned() -> None:
    sid = uuid4()
    big = "x" * (LARGE_THRESHOLD_BYTES + 1000)
    r = maybe_persist_large_tool_result(sid, "tu1", big)
    assert r.persisted_path is not None
    assert r.persisted_path.exists()
    assert r.persisted_path.read_text() == big
    assert "<persisted-output" in r.content_for_model
    assert "tu1" in r.content_for_model
    assert str(r.persisted_path) in r.content_for_model


def test_threshold_boundary_exactly_at() -> None:
    """正好等於 threshold 不持久化(只有大於才寫)。"""
    sid = uuid4()
    boundary = "x" * LARGE_THRESHOLD_BYTES
    r = maybe_persist_large_tool_result(sid, "tu1", boundary)
    assert r.persisted_path is None


def test_generate_preview_truncates() -> None:
    big = "y" * (PREVIEW_MAX_CHARS * 3)
    p = generate_preview(big)
    assert len(p) < len(big)
    assert "truncated" in p


def test_generate_preview_short_unchanged() -> None:
    short = "hello"
    assert generate_preview(short) == short
