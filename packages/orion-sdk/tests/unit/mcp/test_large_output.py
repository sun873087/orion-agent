"""mcp/large_output.py — 25K threshold + 持久化。"""

from __future__ import annotations

from uuid import uuid4

from orion_sdk.mcp.large_output import (
    MCP_LARGE_THRESHOLD_BYTES,
    process_mcp_result,
)


def test_small_result_not_persisted() -> None:
    sid = uuid4()
    r = process_mcp_result(
        session_id=sid, server_name="fs", tool_name="ls",
        raw_result={"items": ["a", "b"]},
    )
    assert r.persisted_path is None
    assert "items" in r.content_for_model


def test_large_result_persisted() -> None:
    sid = uuid4()
    big = {"items": ["x" * 100] * 2000}  # 大量重複,JSON 後肯定 > 100KB
    r = process_mcp_result(
        session_id=sid, server_name="fs", tool_name="ls",
        raw_result=big,
    )
    assert r.persisted_path is not None
    assert r.persisted_path.exists()
    assert "<persisted-mcp-output" in r.content_for_model
    assert "fs" in r.content_for_model
    assert "ls" in r.content_for_model
    assert "jq" in r.content_for_model  # hint 包含 jq 範例


def test_threshold_boundary() -> None:
    """正好等於 threshold 不持久化。"""
    sid = uuid4()
    # JSON dump 一個 N 長字串接近 threshold
    payload = "x" * (MCP_LARGE_THRESHOLD_BYTES - 10)
    r = process_mcp_result(
        session_id=sid, server_name="srv", tool_name="t",
        raw_result=payload,
    )
    assert r.persisted_path is None


def test_str_result_passthrough() -> None:
    sid = uuid4()
    r = process_mcp_result(
        session_id=sid, server_name="x", tool_name="y", raw_result="just a string",
    )
    assert r.content_for_model == "just a string"


def test_filename_safe() -> None:
    """server / tool name 含特殊字 → sanitize 成檔名安全字元。"""
    sid = uuid4()
    big = "x" * (MCP_LARGE_THRESHOLD_BYTES + 1000)
    r = process_mcp_result(
        session_id=sid, server_name="fs/path", tool_name="some@tool",
        raw_result=big,
    )
    assert r.persisted_path is not None
    name = r.persisted_path.name
    assert "/" not in name
    assert "@" not in name
