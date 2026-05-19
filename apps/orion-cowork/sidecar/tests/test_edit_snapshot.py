"""Phase 31-V:edit snapshot + undo turn 驗證。

Storage layer 測試:
  1. snapshot_file 讀檔 → blob;空檔 / 不存在 → None
  2. restore_file 用 blob_id 還原檔內容;blob_id=None → 刪檔(undo Write 新建)
  3. set_last_assistant_metadata 合 patch 進最後一筆 assistant row
  4. find_last_turn_start_index 找最近 user prompt 位置
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_data_dir():
    with tempfile.TemporaryDirectory(prefix="edit-snap-test-") as d:
        old = os.environ.get("ORION_COWORK_DATA_DIR")
        os.environ["ORION_COWORK_DATA_DIR"] = d
        try:
            yield Path(d)
        finally:
            if old is None:
                os.environ.pop("ORION_COWORK_DATA_DIR", None)
            else:
                os.environ["ORION_COWORK_DATA_DIR"] = old


def test_snapshot_file_basic(tmp_data_dir: Path) -> None:
    """讀普通檔 → 拿到 blob_id;檔不存在 → None,0。"""
    from orion_cowork_sidecar import storage
    from orion_cowork_sidecar.edit_snapshot import snapshot_file

    target = tmp_data_dir / "hello.txt"
    target.write_text("hello world\n", encoding="utf-8")

    blob = storage.get_blob_store()
    blob_id, size = snapshot_file(str(target), blob)
    assert blob_id is not None
    assert size == 12  # "hello world\n"
    assert blob.get(blob_id).decode("utf-8") == "hello world\n"

    # 不存在的檔
    bid_none, size_none = snapshot_file(str(tmp_data_dir / "nope.txt"), blob)
    assert bid_none is None
    assert size_none == 0


def test_restore_file_round_trip(tmp_data_dir: Path) -> None:
    """snapshot 後改檔 → restore 還原原內容;blob_id=None → 刪檔。"""
    from orion_cowork_sidecar import storage
    from orion_cowork_sidecar.edit_snapshot import restore_file, snapshot_file

    target = tmp_data_dir / "code.py"
    target.write_text("v1", encoding="utf-8")
    blob = storage.get_blob_store()
    bid, _ = snapshot_file(str(target), blob)

    # 改檔
    target.write_text("v2 — modified", encoding="utf-8")
    assert target.read_text() == "v2 — modified"

    # Restore 還原
    assert restore_file(str(target), bid, blob) is True
    assert target.read_text() == "v1"

    # blob_id=None → 刪檔(模擬 Write 新建後 undo)
    assert restore_file(str(target), None, blob) is True
    assert not target.exists()


@pytest.mark.asyncio
async def test_set_last_assistant_metadata(tmp_data_dir: Path) -> None:
    """append 一個 assistant row,set metadata patch,讀回確認 merge 正確。"""
    from orion_model.types import NormalizedMessage
    from orion_cowork_sidecar import storage

    engine = await storage.init_storage()
    sid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    await storage.save_session_metadata(
        engine, sid, provider="anthropic", model="claude-haiku-4-5",
    )
    await storage.append_messages(engine, sid, [
        NormalizedMessage(role="user", content="Q"),
        NormalizedMessage(role="assistant", content="A"),
    ])
    # Patch 1
    ok = await storage.set_last_assistant_metadata(
        engine, sid, {"edit_snapshots": [{"file_path": "/x", "before_blob_id": "b1"}]},
    )
    assert ok is True
    meta = await storage.get_last_assistant_metadata(engine, sid)
    assert meta == {"edit_snapshots": [{"file_path": "/x", "before_blob_id": "b1"}]}

    # Patch 2(merge,不取代既有)
    ok2 = await storage.set_last_assistant_metadata(
        engine, sid, {"foo": "bar"},
    )
    assert ok2 is True
    meta2 = await storage.get_last_assistant_metadata(engine, sid)
    assert meta2 is not None
    assert meta2.get("edit_snapshots")  # 沒被覆蓋
    assert meta2.get("foo") == "bar"

    await engine.dispose()


@pytest.mark.asyncio
async def test_find_last_turn_start_index(tmp_data_dir: Path) -> None:
    """有 3 個 turn 的 session,find 應該回最後一個 user prompt 的 chronological index。"""
    from orion_model.types import NormalizedMessage
    from orion_cowork_sidecar import storage

    engine = await storage.init_storage()
    sid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    await storage.save_session_metadata(
        engine, sid, provider="anthropic", model="claude-haiku-4-5",
    )
    # 3 turn:U-A、U-A、U-A
    msgs = []
    for i in range(3):
        msgs.append(NormalizedMessage(role="user", content=f"Q{i}"))
        msgs.append(NormalizedMessage(role="assistant", content=f"A{i}"))
    await storage.append_messages(engine, sid, msgs)
    idx = await storage.find_last_turn_start_index(engine, sid)
    # 6 個 rows,最後一筆 user prompt 在 index 4(0-based)
    assert idx == 4
    await engine.dispose()
