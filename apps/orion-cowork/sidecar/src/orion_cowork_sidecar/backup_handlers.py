"""Backup / Restore RPC handlers — 把 `~/.orion/` 打包成 zip / 還原回去。

範圍:
- 包:`sessions/cowork.db`(走 VACUUM INTO snapshot,不卡服務)、`blobs/`
  (toggle)、`skills/`、`users/`、`mcp.json`、`permissions.json`、`plans/`、
  `secrets.enc`、`.master.key`
- 跳:`tts-cache/`(regeneratable)、`sessions/cowork.db-{shm,wal}`(VACUUM
  INTO snapshot 已 commit-only)、`sessions/<uuid>/`(CLI / chat-api JSONL —
  別 host 的 sessions)、`sessions/cli.db`(別 host 的 DB)、`settings.json`
  (CLI / chat-api 才用)

Restore 是**整批 replace**(舊資料先 move-aside 到 `~/.orion.backup-<ts>/`),
完成後 emit `backup.restart_required` notification,UI 引導 user 重啟 app —
sidecar 自己不重啟 process(那是 main 的責任)。
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
import tempfile
import time
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, TYPE_CHECKING

from orion_cowork_sidecar import storage

if TYPE_CHECKING:
    from orion_cowork_sidecar.handlers import Handlers


# 相對 data_dir 的「永遠不包」清單。Path glob 形式,精準 match。
_SKIP_ALWAYS = {
    "tts-cache",                      # 整 dir
    "settings.json",                  # CLI / chat-api 才用
    "sessions/cli.db",                # CLI DB
    "sessions/cowork.db-shm",         # SQLite WAL shared memory
    "sessions/cowork.db-wal",         # SQLite WAL log
    "sessions/cowork.db-journal",     # rollback journal(rare)
}

_MANIFEST_NAME = "manifest.json"
_DB_REL = "sessions/cowork.db"
_BACKUP_SCHEMA_VERSION = 1


# ─── path enumeration ─────────────────────────────────────────────────────


def _is_other_host_session_dir(rel: str) -> bool:
    """`sessions/<uuid>/...` — CLI / chat-api 的 per-session JSONL 目錄,跳過。
    `sessions/cowork.db` 主檔不在這 match 範圍內。
    """
    parts = rel.split("/")
    if len(parts) < 2 or parts[0] != "sessions":
        return False
    name = parts[1]
    if name == "cowork.db":
        return False
    # 任何 sessions/ 下的子目錄(非 cowork.db)都當成別 host 的
    return True


def _should_skip(rel: str) -> bool:
    if rel in _SKIP_ALWAYS:
        return True
    # tts-cache 整個 dir
    if rel == "tts-cache" or rel.startswith("tts-cache/"):
        return True
    if _is_other_host_session_dir(rel):
        return True
    return False


def _walk_backup_files(
    root: Path,
    include_blobs: bool,
) -> list[tuple[str, Path]]:
    """List (rel_path, abs_path) for everything to back up,排除 cowork.db
    主檔(那走 VACUUM snapshot,不直接 copy)。
    """
    out: list[tuple[str, Path]] = []
    if not root.exists():
        return out
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if rel == _DB_REL:
            # cowork.db 自己走 VACUUM INTO snapshot,不直接 copy(避免 WAL race)
            continue
        if _should_skip(rel):
            continue
        if not include_blobs and rel.startswith("blobs/"):
            continue
        out.append((rel, p))
    return out


# ─── size estimation ──────────────────────────────────────────────────────


def _estimate_sizes(root: Path, include_blobs: bool) -> dict[str, int]:
    """回 {db_bytes, blobs_bytes, blobs_count, other_bytes, total_bytes}。"""
    db_path = root / _DB_REL
    db_bytes = db_path.stat().st_size if db_path.exists() else 0

    blobs_dir = root / "blobs"
    blobs_bytes = 0
    blobs_count = 0
    if blobs_dir.exists():
        for p in blobs_dir.rglob("*"):
            if p.is_file():
                blobs_bytes += p.stat().st_size
                blobs_count += 1

    # 算 other(skill / users / mcp.json / 等,排除 cowork.db + blobs + skip 清單)
    other_bytes = 0
    for rel, abs_p in _walk_backup_files(root, include_blobs=False):
        if rel.startswith("blobs/"):
            continue
        other_bytes += abs_p.stat().st_size

    total = db_bytes + other_bytes + (blobs_bytes if include_blobs else 0)
    return {
        "db_bytes": db_bytes,
        "blobs_bytes": blobs_bytes,
        "blobs_count": blobs_count,
        "other_bytes": other_bytes,
        "total_bytes": total,
    }


# ─── DB snapshot ──────────────────────────────────────────────────────────


def _sqlite_vacuum_into(db_path: Path, out_path: Path) -> None:
    """SQLite VACUUM INTO — WAL-safe snapshot,不影響 live writers。"""
    conn = sqlite3.connect(str(db_path))
    try:
        # 確保 target 不存在(VACUUM INTO 要求 target 不存在)
        if out_path.exists():
            out_path.unlink()
        conn.execute(f"VACUUM INTO '{out_path.as_posix()}'")
        conn.commit()
    finally:
        conn.close()


# ─── RPC handlers ─────────────────────────────────────────────────────────


async def backup_preview(
    handlers: "Handlers", params: dict[str, Any]
) -> AsyncIterator[dict[str, Any]]:
    """估算 backup size(讓 UI 在 Export dialog 顯示 + toggle 即時更新)。

    Params:
        include_blobs: bool(default True)
    Yields:
        { event: "backup.preview", data: { db_bytes, blobs_bytes, blobs_count,
          other_bytes, total_bytes }, final: True }
    """
    include_blobs = bool(params.get("include_blobs", True))
    root = storage.data_dir()
    sizes = await asyncio.to_thread(_estimate_sizes, root, include_blobs)
    yield {"event": "backup.preview", "data": sizes, "final": True}


async def backup_export(
    handlers: "Handlers", params: dict[str, Any]
) -> AsyncIterator[dict[str, Any]]:
    """Export `~/.orion/` 成 zip 寫到 `params.target_path`。

    Params:
        target_path: str — 絕對路徑(.zip),Electron showSaveDialog 拿到的
        include_blobs: bool(default True)
    Yields:
        { event: "backup.export_progress", data: { stage, ... } }
        { event: "backup.exported", data: { path, total_bytes, manifest },
          final: True }
        失敗 → { event: "error", data: { code, message }, final: True }
    """
    target_path_raw = params.get("target_path")
    if not isinstance(target_path_raw, str) or not target_path_raw.strip():
        yield {"event": "error",
               "data": {"code": "BAD_PARAMS", "message": "target_path required"},
               "final": True}
        return
    target_path = Path(target_path_raw).expanduser()
    include_blobs = bool(params.get("include_blobs", True))
    root = storage.data_dir()

    if not root.exists():
        yield {"event": "error",
               "data": {"code": "NO_DATA", "message": f"{root} not found"},
               "final": True}
        return

    yield {"event": "backup.export_progress", "data": {"stage": "snapshot_db"}}

    # 1) Snapshot cowork.db via VACUUM INTO into a temp file
    tmp_db: Path | None = None
    db_src = root / _DB_REL
    if db_src.exists():
        tmp_fd, tmp_name = tempfile.mkstemp(prefix="cowork-backup-db-", suffix=".sqlite3")
        os.close(tmp_fd)
        tmp_db = Path(tmp_name)
        try:
            await asyncio.to_thread(_sqlite_vacuum_into, db_src, tmp_db)
        except sqlite3.Error as e:
            tmp_db.unlink(missing_ok=True)
            yield {"event": "error",
                   "data": {"code": "DB_SNAPSHOT_FAILED", "message": str(e)},
                   "final": True}
            return

    yield {"event": "backup.export_progress", "data": {"stage": "scan_files"}}

    files = await asyncio.to_thread(_walk_backup_files, root, include_blobs)

    manifest = {
        "schema_version": _BACKUP_SCHEMA_VERSION,
        "exported_at": int(time.time()),
        "include_blobs": include_blobs,
        "data_dir": str(root),
        "file_count": len(files) + (1 if tmp_db else 0),
        "has_db": tmp_db is not None,
    }

    yield {"event": "backup.export_progress",
           "data": {"stage": "write_zip", "files": len(files)}}

    # 2) Write zip(thread,避免大檔卡 loop)
    def _write_zip() -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(
            target_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
        ) as zf:
            zf.writestr(_MANIFEST_NAME, json.dumps(manifest, indent=2))
            if tmp_db is not None:
                zf.write(tmp_db, arcname=_DB_REL)
            for rel, abs_p in files:
                zf.write(abs_p, arcname=rel)

    try:
        await asyncio.to_thread(_write_zip)
    except OSError as e:
        if tmp_db is not None:
            tmp_db.unlink(missing_ok=True)
        yield {"event": "error",
               "data": {"code": "ZIP_WRITE_FAILED", "message": str(e)},
               "final": True}
        return
    finally:
        if tmp_db is not None:
            tmp_db.unlink(missing_ok=True)

    final_size = target_path.stat().st_size
    yield {"event": "backup.exported",
           "data": {"path": str(target_path),
                    "total_bytes": final_size,
                    "manifest": manifest},
           "final": True}


async def backup_inspect(
    handlers: "Handlers", params: dict[str, Any]
) -> AsyncIterator[dict[str, Any]]:
    """讀 zip 的 manifest.json 給 UI 在 Restore confirm 顯示。

    Params:
        source_path: str — 絕對路徑(.zip)
    Yields:
        { event: "backup.inspected", data: { manifest, zip_size }, final: True }
    """
    src_raw = params.get("source_path")
    if not isinstance(src_raw, str) or not src_raw.strip():
        yield {"event": "error",
               "data": {"code": "BAD_PARAMS", "message": "source_path required"},
               "final": True}
        return
    src = Path(src_raw).expanduser()
    if not src.is_file():
        yield {"event": "error",
               "data": {"code": "NOT_FOUND", "message": f"{src} not found"},
               "final": True}
        return

    def _read_manifest() -> dict[str, Any] | None:
        try:
            with zipfile.ZipFile(src, "r") as zf:
                with zf.open(_MANIFEST_NAME) as fh:
                    return json.load(fh)
        except (KeyError, zipfile.BadZipFile, json.JSONDecodeError):
            return None

    manifest = await asyncio.to_thread(_read_manifest)
    if manifest is None:
        yield {"event": "error",
               "data": {"code": "BAD_BACKUP",
                        "message": "missing or invalid manifest.json"},
               "final": True}
        return
    if manifest.get("schema_version") != _BACKUP_SCHEMA_VERSION:
        yield {"event": "error",
               "data": {"code": "SCHEMA_MISMATCH",
                        "message": f"backup schema {manifest.get('schema_version')!r} "
                                   f"!= expected {_BACKUP_SCHEMA_VERSION}"},
               "final": True}
        return

    yield {"event": "backup.inspected",
           "data": {"manifest": manifest, "zip_size": src.stat().st_size},
           "final": True}


async def backup_restore(
    handlers: "Handlers", params: dict[str, Any]
) -> AsyncIterator[dict[str, Any]]:
    """Move 現有 `~/.orion/` → `~/.orion.backup-<ts>/`,unzip 進新的 `~/.orion/`。

    完成後 emit `backup.restart_required`(handlers.notify);UI 引導 user 按
    Restart。Sidecar 不自殺 — 那是 main process 的責任。

    Params:
        source_path: str — 絕對路徑(.zip)
    Yields:
        { event: "backup.restore_progress", data: { stage, ... } }
        { event: "backup.restored", data: { moved_to }, final: True }
    """
    src_raw = params.get("source_path")
    if not isinstance(src_raw, str) or not src_raw.strip():
        yield {"event": "error",
               "data": {"code": "BAD_PARAMS", "message": "source_path required"},
               "final": True}
        return
    src = Path(src_raw).expanduser()
    if not src.is_file():
        yield {"event": "error",
               "data": {"code": "NOT_FOUND", "message": f"{src} not found"},
               "final": True}
        return

    # 確認 zip 合法 + schema 對
    def _verify() -> dict[str, Any] | None:
        try:
            with zipfile.ZipFile(src, "r") as zf:
                if _MANIFEST_NAME not in zf.namelist():
                    return None
                with zf.open(_MANIFEST_NAME) as fh:
                    return json.load(fh)
        except (zipfile.BadZipFile, json.JSONDecodeError):
            return None

    manifest = await asyncio.to_thread(_verify)
    if manifest is None or manifest.get("schema_version") != _BACKUP_SCHEMA_VERSION:
        yield {"event": "error",
               "data": {"code": "BAD_BACKUP",
                        "message": "invalid manifest or schema mismatch"},
               "final": True}
        return

    root = storage.data_dir()
    yield {"event": "backup.restore_progress",
           "data": {"stage": "close_engine"}}

    # 1) 關 DB engine + scheduler — restore 後一切 cached state 都失效
    try:
        if handlers._engine is not None:
            await handlers._engine.dispose()
            handlers._engine = None
    except Exception:  # noqa: BLE001
        pass
    try:
        await handlers._scheduler.stop()
        handlers._scheduler_started = False
    except Exception:  # noqa: BLE001
        pass

    # 2) Move aside
    ts = time.strftime("%Y%m%d-%H%M%S")
    moved_to = root.parent / f"{root.name}.backup-{ts}"
    yield {"event": "backup.restore_progress",
           "data": {"stage": "move_aside", "moved_to": str(moved_to)}}

    def _move_aside() -> None:
        if root.exists():
            shutil.move(str(root), str(moved_to))
        root.mkdir(parents=True, exist_ok=True)

    try:
        await asyncio.to_thread(_move_aside)
    except OSError as e:
        yield {"event": "error",
               "data": {"code": "MOVE_FAILED", "message": str(e)},
               "final": True}
        return

    # 3) Unzip 進 root
    yield {"event": "backup.restore_progress", "data": {"stage": "extract"}}

    def _extract() -> None:
        with zipfile.ZipFile(src, "r") as zf:
            for info in zf.infolist():
                if info.filename == _MANIFEST_NAME:
                    continue
                # zipfile 對外提取會處理目錄,但要防 path traversal
                name = info.filename
                if name.startswith("/") or ".." in Path(name).parts:
                    continue
                zf.extract(info, root)

    try:
        await asyncio.to_thread(_extract)
    except (zipfile.BadZipFile, OSError) as e:
        yield {"event": "error",
               "data": {"code": "EXTRACT_FAILED", "message": str(e)},
               "final": True}
        return

    # 4) 通知 UI 重啟
    await handlers.notify({
        "event": "backup.restart_required",
        "data": {"reason": "restore_complete", "moved_to": str(moved_to)},
    })

    yield {"event": "backup.restored",
           "data": {"moved_to": str(moved_to),
                    "manifest": manifest},
           "final": True}


__all__ = [
    "backup_export",
    "backup_inspect",
    "backup_preview",
    "backup_restore",
]
