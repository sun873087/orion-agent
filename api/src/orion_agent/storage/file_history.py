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
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from orion_agent.storage.paths import session_paths


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
    return SnapshotResult(
        snapshot_path=snap_path,
        content_hash=content_hash,
        original_size=len(data),
    )
