"""Backup / Restore round-trip tests。

不打 RPC server,直接呼 backup_handlers + 模擬 Handlers 物件提供必要 attribute。
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import pytest

from orion_cowork_sidecar import backup_handlers


class _FakeHandlers:
    """簡化版 Handlers — backup_handlers 只摸 _engine / _scheduler / notify。"""

    def __init__(self) -> None:
        self._engine = None
        self._scheduler_started = False
        # scheduler 需要 .stop() 是 async no-op
        class _NoopScheduler:
            async def stop(self) -> None:
                return None
        self._scheduler = _NoopScheduler()
        self.notifications: list[dict[str, Any]] = []

    async def notify(self, frame: dict[str, Any]) -> None:
        self.notifications.append(frame)


@pytest.fixture
def fake_orion_dir():
    """tmpdir 當 ~/.orion/。塞點假資料:cowork.db + blobs + skills + users/memory + mcp.json。"""
    with tempfile.TemporaryDirectory(prefix="backup-test-") as d:
        old = os.environ.get("ORION_COWORK_DATA_DIR")
        os.environ["ORION_COWORK_DATA_DIR"] = d
        root = Path(d)

        # 1) cowork.db — 真 SQLite 檔(VACUUM INTO 需要),塞點資料
        (root / "sessions").mkdir(parents=True)
        db_path = root / "sessions" / "cowork.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE t (k TEXT, v TEXT)")
        conn.execute("INSERT INTO t VALUES ('alpha', 'aaa')")
        conn.execute("INSERT INTO t VALUES ('beta', 'bbb')")
        conn.commit()
        conn.close()

        # 2) blobs/
        blobs = root / "blobs"
        blobs.mkdir()
        (blobs / "deadbeef.bin").write_bytes(b"BLOB-CONTENT-1")
        (blobs / "cafebabe.bin").write_bytes(b"BLOB-CONTENT-2-x" * 100)

        # 3) skills/
        skill = root / "skills" / "test-skill"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("# test skill\n")

        # 4) users/<u>/memory/
        mem = root / "users" / "cowork-local" / "memory"
        mem.mkdir(parents=True)
        (mem / "MEMORY.md").write_text("- [Hello](hi.md)\n")
        (mem / "hi.md").write_text("---\nname: hi\n---\n\ncontent\n")

        # 5) mcp.json + permissions.json
        (root / "mcp.json").write_text('{"mcpServers": {}}')
        (root / "permissions.json").write_text("[]")

        # 6) 要被跳的東西
        (root / "tts-cache").mkdir()
        (root / "tts-cache" / "abc.mp3").write_bytes(b"FAKE-TTS-AUDIO")
        (root / "settings.json").write_text('{"foo": 1}')  # CLI / chat-api only
        (root / "sessions" / "cli.db").write_bytes(b"CLI-DB-DATA")
        # 別 host 的 JSONL session dir
        other = root / "sessions" / "11111111-2222-3333-4444-555555555555"
        other.mkdir()
        (other / "transcript.jsonl").write_text("{}\n")

        try:
            yield root
        finally:
            if old is None:
                os.environ.pop("ORION_COWORK_DATA_DIR", None)
            else:
                os.environ["ORION_COWORK_DATA_DIR"] = old


async def _drain(gen) -> list[dict[str, Any]]:
    out = []
    async for ev in gen:
        out.append(ev)
    return out


def _last_final(events: list[dict[str, Any]]) -> dict[str, Any]:
    return next(ev for ev in events if ev.get("final"))


# ─── tests ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_preview_includes_blobs_by_default(fake_orion_dir: Path) -> None:
    handlers = _FakeHandlers()
    events = await _drain(backup_handlers.backup_preview(handlers, {}))
    final = _last_final(events)
    data = final["data"]
    assert data["db_bytes"] > 0
    assert data["blobs_count"] == 2
    assert data["blobs_bytes"] > 0
    # total = db + other + blobs(default include)
    assert data["total_bytes"] == data["db_bytes"] + data["other_bytes"] + data["blobs_bytes"]


@pytest.mark.asyncio
async def test_preview_exclude_blobs_changes_total(fake_orion_dir: Path) -> None:
    handlers = _FakeHandlers()
    events = await _drain(
        backup_handlers.backup_preview(handlers, {"include_blobs": False})
    )
    data = _last_final(events)["data"]
    # blobs_bytes 還是有報(讓 UI 顯示估算),但 total 不算
    assert data["total_bytes"] == data["db_bytes"] + data["other_bytes"]
    assert data["blobs_count"] == 2  # info 還在,只是 total 不計


@pytest.mark.asyncio
async def test_export_writes_zip_with_db_and_blobs(fake_orion_dir: Path) -> None:
    handlers = _FakeHandlers()
    with tempfile.TemporaryDirectory(prefix="backup-out-") as out_dir:
        target = Path(out_dir) / "my-backup.zip"
        events = await _drain(
            backup_handlers.backup_export(
                handlers, {"target_path": str(target), "include_blobs": True}
            )
        )
        final = _last_final(events)
        assert final["event"] == "backup.exported"
        assert target.exists()

        with zipfile.ZipFile(target, "r") as zf:
            names = set(zf.namelist())
            assert "manifest.json" in names
            assert "sessions/cowork.db" in names
            assert "blobs/deadbeef.bin" in names
            assert "blobs/cafebabe.bin" in names
            assert "skills/test-skill/SKILL.md" in names
            assert "users/cowork-local/memory/MEMORY.md" in names
            assert "users/cowork-local/memory/hi.md" in names
            assert "mcp.json" in names
            assert "permissions.json" in names

            # 跳過的東西不該出現
            assert "tts-cache/abc.mp3" not in names
            assert "settings.json" not in names
            assert "sessions/cli.db" not in names
            assert not any(n.startswith("sessions/11111111") for n in names)

            # 確認 DB 是 VACUUM 後的 snapshot — 不是 0-byte
            assert zf.getinfo("sessions/cowork.db").file_size > 0


@pytest.mark.asyncio
async def test_export_exclude_blobs(fake_orion_dir: Path) -> None:
    handlers = _FakeHandlers()
    with tempfile.TemporaryDirectory(prefix="backup-out-") as out_dir:
        target = Path(out_dir) / "no-blobs.zip"
        await _drain(
            backup_handlers.backup_export(
                handlers, {"target_path": str(target), "include_blobs": False}
            )
        )
        with zipfile.ZipFile(target, "r") as zf:
            names = set(zf.namelist())
            assert "sessions/cowork.db" in names
            assert not any(n.startswith("blobs/") for n in names)


@pytest.mark.asyncio
async def test_inspect_returns_manifest(fake_orion_dir: Path) -> None:
    handlers = _FakeHandlers()
    with tempfile.TemporaryDirectory(prefix="backup-out-") as out_dir:
        target = Path(out_dir) / "to-inspect.zip"
        await _drain(
            backup_handlers.backup_export(
                handlers, {"target_path": str(target), "include_blobs": True}
            )
        )
        events = await _drain(
            backup_handlers.backup_inspect(handlers, {"source_path": str(target)})
        )
        final = _last_final(events)
        assert final["event"] == "backup.inspected"
        m = final["data"]["manifest"]
        assert m["schema_version"] == 1
        assert m["include_blobs"] is True
        assert m["has_db"] is True


@pytest.mark.asyncio
async def test_inspect_rejects_bad_zip(fake_orion_dir: Path) -> None:
    handlers = _FakeHandlers()
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
        f.write(b"not a zip")
        path = f.name
    try:
        events = await _drain(
            backup_handlers.backup_inspect(handlers, {"source_path": path})
        )
        err = _last_final(events)
        assert err["event"] == "error"
        assert err["data"]["code"] == "BAD_BACKUP"
    finally:
        Path(path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_round_trip_export_then_restore(fake_orion_dir: Path) -> None:
    """Export → 摧毀現有 data → Restore → 內容應全回來。"""
    handlers = _FakeHandlers()
    with tempfile.TemporaryDirectory(prefix="backup-out-") as out_dir:
        target = Path(out_dir) / "round.zip"
        await _drain(
            backup_handlers.backup_export(
                handlers, {"target_path": str(target), "include_blobs": True}
            )
        )

        # 摧毀部分檔讓我們能驗證真的被 restore
        (fake_orion_dir / "blobs" / "deadbeef.bin").unlink()
        (fake_orion_dir / "mcp.json").write_text('{"replaced": true}')

        # Restore
        events = await _drain(
            backup_handlers.backup_restore(handlers, {"source_path": str(target)})
        )
        final = _last_final(events)
        assert final["event"] == "backup.restored"

        # 1) blob 回來了
        assert (fake_orion_dir / "blobs" / "deadbeef.bin").read_bytes() == b"BLOB-CONTENT-1"
        # 2) mcp.json 被覆蓋回原內容
        assert json.loads((fake_orion_dir / "mcp.json").read_text()) == {"mcpServers": {}}
        # 3) cowork.db 可開,內容對
        db = fake_orion_dir / "sessions" / "cowork.db"
        assert db.exists()
        conn = sqlite3.connect(str(db))
        rows = conn.execute("SELECT k, v FROM t ORDER BY k").fetchall()
        conn.close()
        assert rows == [("alpha", "aaa"), ("beta", "bbb")]

        # 4) restart notification 有送出
        assert any(n["event"] == "backup.restart_required" for n in handlers.notifications)

        # 5) move-aside dir 存在且帶舊資料(被搬走的)
        moved_to = Path(final["data"]["moved_to"])
        assert moved_to.exists()
        assert (moved_to / "tts-cache" / "abc.mp3").exists()


@pytest.mark.asyncio
async def test_restore_rejects_invalid_zip(fake_orion_dir: Path) -> None:
    handlers = _FakeHandlers()
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
        f.write(b"garbage")
        path = f.name
    try:
        events = await _drain(
            backup_handlers.backup_restore(handlers, {"source_path": path})
        )
        err = _last_final(events)
        assert err["event"] == "error"
        # 原 data_dir 沒被動(restore 沒到 move-aside 階段)
        assert (fake_orion_dir / "sessions" / "cowork.db").exists()
    finally:
        Path(path).unlink(missing_ok=True)
