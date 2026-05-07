"""storage/mcp_output.py — Phase 5 真實實作(persist_mcp_binary / load_mcp_binary)。"""

from __future__ import annotations

import json
from uuid import uuid4

from orion_agent.storage.mcp_output import (
    decode_b64,
    load_mcp_binary,
    persist_mcp_binary,
)


def test_persist_and_load_png() -> None:
    sid = uuid4()
    data = b"\x89PNG\r\n\x1a\n" + b"x" * 100
    path = persist_mcp_binary(sid, "tu_001", "image/png", data)
    assert path.exists()
    assert path.suffix == ".png"

    loaded = load_mcp_binary(sid, "tu_001")
    assert loaded is not None
    assert loaded["media_type"] == "image/png"
    assert loaded["size"] == len(data)
    assert loaded["path"] == path

    # meta sidecar 存在
    meta_path = path.with_suffix(path.suffix + ".meta.json")
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text())
    assert meta["tool_use_id"] == "tu_001"


def test_load_missing_returns_none() -> None:
    sid = uuid4()
    assert load_mcp_binary(sid, "nonexistent") is None


def test_decode_b64() -> None:
    raw = b"hello"
    import base64
    encoded = base64.b64encode(raw).decode()
    assert decode_b64(encoded) == raw


def test_unknown_media_type_uses_bin_extension() -> None:
    sid = uuid4()
    path = persist_mcp_binary(sid, "tu_x", "application/x-weird", b"\x00\x01")
    assert path.suffix == ".bin"


def test_special_chars_in_tool_use_id() -> None:
    """tool_use_id 含 / 應 sanitize。"""
    sid = uuid4()
    path = persist_mcp_binary(sid, "weird/id@here", "image/png", b"x")
    assert "/" not in path.name
    assert "@" not in path.name
