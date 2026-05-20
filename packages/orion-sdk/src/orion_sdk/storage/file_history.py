"""File history snapshot — 寫前快照,supports undo / 審計。

對應 TS Claude Code `src/utils/fileHistory.ts`。

設計:
- FileWriteTool / FileEditTool 寫入前先 call `make_snapshot(session_id, file_path)`
- 若原檔不存在 → no-op(沒東西可快照)
- 若原檔存在 → 讀內容 + content hash + 寫到 file-history/<hash>.snap
- 同 hash 的檔已存在 → no-op(重複內容不重複寫)
- 回傳 snapshot 路徑(若有)+ 原 hash

Snapshot 檔內容格式:
    # snapshot of /absolute/path/to/original
    # session: <session-id>
    # captured: <ISO datetime>
    # original_size: <bytes>
    ---SNAPSHOT---
    <原檔完整內容>
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from orion_sdk.storage.paths import session_paths

_DEFAULT_MAX_SNAPSHOTS = 100


def _max_snapshots_from_env() -> int:
    """從 ORION_FILE_HISTORY_MAX_SNAPSHOTS 讀上限。

    無效值(非整數 / 負數)fallback 預設 100。0 視為「不 prune」(避免 user 誤踩)。
    """
    raw = os.environ.get("ORION_FILE_HISTORY_MAX_SNAPSHOTS")
    if raw:
        try:
            v = int(raw)
            if v > 0:
                return v
        except ValueError:
            pass
    return _DEFAULT_MAX_SNAPSHOTS


def prune_old_snapshots(session_id: UUID, max_count: int) -> int:
    """按 mtime 排序刪 file-history 內超量的舊 snapshot。

    Args:
        session_id: 對應 file_history_dir
        max_count: 保留上限;<= 0 視為「不 prune」直接 return 0

    Returns:
        被刪掉的檔案數(0 表示沒事可做)。
    """
    if max_count <= 0:
        return 0
    sp = session_paths(session_id)
    history_dir = sp.file_history_dir
    if not history_dir.is_dir():
        return 0

    snaps = list(history_dir.glob("*.snap"))
    if len(snaps) <= max_count:
        return 0

    # 按 mtime 升冪 — 最舊在前
    snaps.sort(key=lambda p: p.stat().st_mtime)
    to_delete = snaps[: len(snaps) - max_count]
    deleted = 0
    for p in to_delete:
        try:
            p.unlink()
            deleted += 1
        except OSError:
            # 檔案可能同時被別處刪了 — 跳過,不擋住其他
            continue
    return deleted


@dataclass(frozen=True)
class SnapshotResult:
    """make_snapshot 回傳。"""

    snapshot_path: Path | None
    """snapshot 檔位置;None 表示沒快照(原檔不存在或為空)。"""

    content_hash: str | None
    """原檔內容的 SHA256;None 同上。"""

    original_size: int = 0


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def make_snapshot(
    session_id: UUID,
    file_path: Path | str,
) -> SnapshotResult:
    """快照 file_path 的當前內容到 session 的 file-history/。

    Args:
        session_id: 用以推算 file-history 路徑
        file_path: 要快照的檔案絕對路徑(可為 str 或 Path)

    Returns:
        SnapshotResult:含 snapshot_path(若有寫)、content_hash、original_size
    """
    src = Path(file_path)

    if not src.is_absolute():
        # 相對路徑不快照(無法可靠定位)
        return SnapshotResult(snapshot_path=None, content_hash=None)

    if not src.exists() or not src.is_file():
        return SnapshotResult(snapshot_path=None, content_hash=None)

    try:
        data = src.read_bytes()
    except OSError:
        return SnapshotResult(snapshot_path=None, content_hash=None)

    content_hash = _hash_bytes(data)
    sp = session_paths(session_id)
    sp.ensure_dirs()
    snap_path = sp.file_history_path(content_hash)

    # 同 hash 的檔已存在 → 無需重複寫
    if snap_path.exists():
        return SnapshotResult(
            snapshot_path=snap_path,
            content_hash=content_hash,
            original_size=len(data),
        )

    captured = datetime.now(UTC).isoformat()
    header = (
        f"# snapshot of {src}\n"
        f"# session: {session_id}\n"
        f"# captured: {captured}\n"
        f"# original_size: {len(data)}\n"
        f"---SNAPSHOT---\n"
    )
    snap_path.write_bytes(header.encode("utf-8") + data)

    # 寫成功 → prune 超量舊 snapshot。dedupe 路徑(snap_path 早已存在)
    # 不會走到這裡,避免重複工作。
    prune_old_snapshots(session_id, _max_snapshots_from_env())

    return SnapshotResult(
        snapshot_path=snap_path,
        content_hash=content_hash,
        original_size=len(data),
    )
