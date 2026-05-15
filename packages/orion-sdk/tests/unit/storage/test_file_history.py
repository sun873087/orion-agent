"""storage/file_history.py。"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from orion_sdk.storage.file_history import make_snapshot


def test_snapshot_existing_file(tmp_path: Path) -> None:
    src = tmp_path / "f.txt"
    src.write_text("hello world", encoding="utf-8")
    sid = uuid4()
    r = make_snapshot(sid, src)
    assert r.snapshot_path is not None
    assert r.snapshot_path.exists()
    assert r.content_hash is not None
    body = r.snapshot_path.read_bytes()
    assert b"---SNAPSHOT---" in body
    assert b"hello world" in body
    assert r.original_size == len("hello world")


def test_snapshot_missing_file_noop(tmp_path: Path) -> None:
    src = tmp_path / "absent.txt"
    sid = uuid4()
    r = make_snapshot(sid, src)
    assert r.snapshot_path is None
    assert r.content_hash is None


def test_snapshot_relative_path_rejected() -> None:
    sid = uuid4()
    r = make_snapshot(sid, "relative.txt")
    assert r.snapshot_path is None


def test_snapshot_dedupe_same_hash(tmp_path: Path) -> None:
    src = tmp_path / "f.txt"
    src.write_text("abc", encoding="utf-8")
    sid = uuid4()

    r1 = make_snapshot(sid, src)
    assert r1.snapshot_path is not None
    mtime1 = r1.snapshot_path.stat().st_mtime

    # 第二次同 hash → 不重寫,mtime 不變
    r2 = make_snapshot(sid, src)
    assert r2.snapshot_path == r1.snapshot_path
    assert r2.snapshot_path.stat().st_mtime == mtime1
