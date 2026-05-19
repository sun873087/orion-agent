"""File edit snapshot — Phase 31-V(Diff viewer + Undo turn 共用基底)。

每次 Edit / Write / NotebookEdit 跑之前讀檔 → put blob;跑完再讀 → put blob;
兩個 blob_id 寫進 assistant 訊息 metadata_json,renderer 可以拿來:
  1. 顯 inline diff(diff viewer)
  2. 整輪 undo 時 restore before 內容

blob_store 本來就 content-addressed(同檔多次 edit → 共用 blob),小 file 幾乎
免費。> SNAPSHOT_MAX_BYTES 不 snapshot — 太大檔通常不適合 inline diff。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orion_cowork_sidecar.blob_store import BlobStore


# 1 MiB 上限 — 比這大的檔 snapshot 沒實用性(diff viewer 也讀不完),且 blob
# store 不該被 100MB log 檔塞滿
SNAPSHOT_MAX_BYTES = 1 * 1024 * 1024

# 我們關心的 tool name(SDK 都用 path 欄位)
SNAPSHOTTED_TOOLS = frozenset({"Edit", "Write", "NotebookEdit"})


def is_snapshottable_tool(tool_name: str) -> bool:
    return tool_name in SNAPSHOTTED_TOOLS


def extract_file_path(tool_input: dict) -> str | None:
    """三個 tool 都用 `path` 欄位(SDK 統一)。"""
    p = tool_input.get("path")
    return p if isinstance(p, str) and p else None


def snapshot_file(path: str, blob: "BlobStore") -> tuple[str | None, int]:
    """讀檔 → put blob,回 (blob_id, size_bytes)。

    - 檔不存在 → (None, 0)
    - 讀失敗(權限 / decode 等)→ (None, 0)
    - 大於 SNAPSHOT_MAX_BYTES → (None, size)只回大小不 put
    """
    p = Path(path).expanduser()
    if not p.is_file():
        return None, 0
    try:
        size = p.stat().st_size
    except OSError:
        return None, 0
    if size > SNAPSHOT_MAX_BYTES:
        return None, size
    try:
        raw = p.read_bytes()
    except OSError:
        return None, 0
    blob_id = blob.put(raw)
    return blob_id, size


def read_blob_text(blob_id: str, blob: "BlobStore") -> str:
    """讀 blob 並 decode 成 utf-8;非 utf-8(binary)回 hex placeholder。
    Renderer 顯 diff 時 fallback「(binary)」。"""
    raw = blob.get(blob_id)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return f"(binary {len(raw)} bytes)"


def restore_file(path: str, blob_id: str | None, blob: "BlobStore") -> bool:
    """Undo 用:把檔還原成 before 狀態。

    - blob_id is None → before 為「檔不存在」(Write 新建)→ 刪掉現在的檔
    - blob_id 給 → 讀 blob 寫回檔(覆蓋目前內容)
    回 True 表示有動到。fail return False。
    """
    p = Path(path).expanduser()
    if blob_id is None:
        # 原本檔不存在,Write 創出來的 → 刪
        if p.exists():
            try:
                p.unlink()
                return True
            except OSError:
                return False
        return True
    # 還原內容
    try:
        raw = blob.get(blob_id)
    except FileNotFoundError:
        return False
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw)
        return True
    except OSError:
        return False


__all__ = [
    "SNAPSHOTTED_TOOLS",
    "SNAPSHOT_MAX_BYTES",
    "extract_file_path",
    "is_snapshottable_tool",
    "read_blob_text",
    "restore_file",
    "snapshot_file",
]
