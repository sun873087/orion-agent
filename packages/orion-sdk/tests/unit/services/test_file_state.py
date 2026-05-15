"""FileStateCache + Edit/Write 整合測試。Phase 12。"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent
from orion_sdk.services.file_state import (
    FileSnapshot,
    FileStateCache,
    require_fresh_read,
)
from orion_sdk.tools.file.edit import FileEditInput, FileEditTool
from orion_sdk.tools.file.read import FileReadInput, FileReadTool
from orion_sdk.tools.file.write import FileWriteInput, FileWriteTool

# ─── FileStateCache 單元 ────────────────────────────────────────────────────


def test_record_then_has_been_read(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    p.write_text("x")
    c = FileStateCache()
    assert not c.has_been_read(p)
    c.record_read(p)
    assert c.has_been_read(p)
    assert not c.is_stale(p)


def test_external_modification_makes_stale(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    p.write_text("x")
    c = FileStateCache()
    c.record_read(p)
    assert not c.is_stale(p)

    # 外部修改:寫不同內容 + 強制改 mtime
    time.sleep(0.01)
    p.write_text("changed content")
    new_time = time.time() + 1
    os.utime(p, (new_time, new_time))
    assert c.is_stale(p)


def test_unread_file_is_stale(tmp_path: Path) -> None:
    p = tmp_path / "x.txt"
    p.write_text("x")
    c = FileStateCache()
    assert c.is_stale(p)


def test_record_nonexistent_no_op(tmp_path: Path) -> None:
    c = FileStateCache()
    c.record_read(tmp_path / "missing.txt")
    assert not c.has_been_read(tmp_path / "missing.txt")


def test_invalidate(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    p.write_text("x")
    c = FileStateCache()
    c.record_read(p)
    c.invalidate(p)
    assert not c.has_been_read(p)


def test_in_operator(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    p.write_text("x")
    c = FileStateCache()
    c.record_read(p)
    assert p in c
    assert (tmp_path / "missing.txt") not in c


def test_require_fresh_read_no_cache_passes() -> None:
    """cache=None → 不強制(向後相容)。"""
    assert require_fresh_read(None, Path("/anything")) is None


def test_require_fresh_read_unread(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    p.write_text("x")
    c = FileStateCache()
    msg = require_fresh_read(c, p)
    assert msg is not None
    assert "Read" in msg


def test_require_fresh_read_stale(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    p.write_text("x")
    c = FileStateCache()
    c.record_read(p)
    p.write_text("changed")
    new_time = time.time() + 1
    os.utime(p, (new_time, new_time))
    msg = require_fresh_read(c, p)
    assert msg is not None
    assert "modified externally" in msg.lower() or "re-read" in msg.lower()


# ─── 整合 Read / Edit / Write tool ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_read_records_in_cache(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    p.write_text("hello\n")
    cache = FileStateCache()
    ctx = AgentContext(file_state_cache=cache)

    [_ async for _ in FileReadTool().call(FileReadInput(path=str(p)), ctx)]
    assert cache.has_been_read(p)


@pytest.mark.asyncio
async def test_edit_without_read_blocked(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    p.write_text("hello\n")
    cache = FileStateCache()
    ctx = AgentContext(file_state_cache=cache)

    events = [
        e async for e in FileEditTool().call(
            FileEditInput(path=str(p), old_string="hello", new_string="hi"),
            ctx,
        )
    ]
    assert isinstance(events[0], ErrorEvent)
    assert "Read" in events[0].message


@pytest.mark.asyncio
async def test_edit_after_read_works(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    p.write_text("hello\n")
    cache = FileStateCache()
    ctx = AgentContext(file_state_cache=cache)

    [_ async for _ in FileReadTool().call(FileReadInput(path=str(p)), ctx)]
    events = [
        e async for e in FileEditTool().call(
            FileEditInput(path=str(p), old_string="hello", new_string="hi"),
            ctx,
        )
    ]
    assert isinstance(events[0], TextEvent)
    assert p.read_text() == "hi\n"


@pytest.mark.asyncio
async def test_edit_after_external_modification_blocked(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    p.write_text("hello\n")
    cache = FileStateCache()
    ctx = AgentContext(file_state_cache=cache)

    [_ async for _ in FileReadTool().call(FileReadInput(path=str(p)), ctx)]

    # 模擬外部修改
    p.write_text("hello changed\n")
    new_time = time.time() + 1
    os.utime(p, (new_time, new_time))

    events = [
        e async for e in FileEditTool().call(
            FileEditInput(path=str(p), old_string="hello", new_string="hi"),
            ctx,
        )
    ]
    assert isinstance(events[0], ErrorEvent)
    assert "modified externally" in events[0].message.lower() or "re-read" in events[0].message.lower()


@pytest.mark.asyncio
async def test_edit_then_re_edit_works(tmp_path: Path) -> None:
    """Edit 完成後 cache 自動更新 — 連續 Edit 不需要重 Read。"""
    p = tmp_path / "a.txt"
    p.write_text("foo bar baz\n")
    cache = FileStateCache()
    ctx = AgentContext(file_state_cache=cache)

    [_ async for _ in FileReadTool().call(FileReadInput(path=str(p)), ctx)]
    [
        _
        async for _ in FileEditTool().call(
            FileEditInput(path=str(p), old_string="foo", new_string="qux"),
            ctx,
        )
    ]
    # 第 2 次 Edit 不該被當作 stale
    events = [
        e async for e in FileEditTool().call(
            FileEditInput(path=str(p), old_string="bar", new_string="zap"),
            ctx,
        )
    ]
    assert isinstance(events[0], TextEvent)
    assert p.read_text() == "qux zap baz\n"


@pytest.mark.asyncio
async def test_write_new_file_no_read_required(tmp_path: Path) -> None:
    """Write 新檔(原本不存在) → 不要求 Read。"""
    p = tmp_path / "new.txt"
    cache = FileStateCache()
    ctx = AgentContext(file_state_cache=cache)
    events = [
        e async for e in FileWriteTool().call(
            FileWriteInput(path=str(p), content="hi"),
            ctx,
        )
    ]
    assert isinstance(events[0], TextEvent)
    assert p.read_text() == "hi"
    # Write 完應該也 record snapshot
    assert cache.has_been_read(p)


@pytest.mark.asyncio
async def test_write_overwrite_requires_read(tmp_path: Path) -> None:
    """Write 覆蓋既有檔 → 必須先 Read 過。"""
    p = tmp_path / "exists.txt"
    p.write_text("original")
    cache = FileStateCache()
    ctx = AgentContext(file_state_cache=cache)

    events = [
        e async for e in FileWriteTool().call(
            FileWriteInput(path=str(p), content="overwrite"),
            ctx,
        )
    ]
    assert isinstance(events[0], ErrorEvent)


@pytest.mark.asyncio
async def test_write_overwrite_after_read_works(tmp_path: Path) -> None:
    p = tmp_path / "exists.txt"
    p.write_text("original")
    cache = FileStateCache()
    ctx = AgentContext(file_state_cache=cache)

    [_ async for _ in FileReadTool().call(FileReadInput(path=str(p)), ctx)]
    events = [
        e async for e in FileWriteTool().call(
            FileWriteInput(path=str(p), content="overwrite"),
            ctx,
        )
    ]
    assert isinstance(events[0], TextEvent)
    assert p.read_text() == "overwrite"


@pytest.mark.asyncio
async def test_no_cache_means_no_check(tmp_path: Path) -> None:
    """ctx.file_state_cache=None → 跳過所有檢查(向後相容)。"""
    p = tmp_path / "a.txt"
    p.write_text("hello\n")
    ctx = AgentContext()  # 沒 file_state_cache
    events = [
        e async for e in FileEditTool().call(
            FileEditInput(path=str(p), old_string="hello", new_string="hi"),
            ctx,
        )
    ]
    assert isinstance(events[0], TextEvent)


# Sanity:FileSnapshot 是 frozen
def test_snapshot_frozen(tmp_path: Path) -> None:
    snap = FileSnapshot(path=tmp_path, mtime_ns=0, size=0)
    with pytest.raises((AttributeError, Exception)):
        snap.size = 999  # type: ignore[misc]
