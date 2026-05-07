"""Per-session 路徑管理。對應 TS `src/utils/sessionPaths.ts`。

預設 ~/.orion/sessions/<session-id>/
  ├─ transcript.jsonl          conversation 訊息歷史
  ├─ tool-results/
  │   └─ <tool_use_id>.txt     大結果持久化
  ├─ file-history/
  │   └─ <hash>.snap            Edit/Write 寫前快照
  └─ meta.json                  session 元資料(start_time、provider、model)

可由 ORION_SESSIONS_DIR 環境變數覆蓋根路徑。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID


def default_session_root() -> Path:
    """根目錄。預設 ~/.orion/sessions/。可由 ORION_SESSIONS_DIR 覆蓋。"""
    raw = os.environ.get("ORION_SESSIONS_DIR")
    if raw:
        return Path(raw)
    return Path.home() / ".orion" / "sessions"


@dataclass(frozen=True)
class SessionPaths:
    """單一 session 的所有 sub-paths。"""

    session_id: UUID
    root: Path
    """session 根目錄(已含 session_id)。"""

    @property
    def transcript(self) -> Path:
        return self.root / "transcript.jsonl"

    @property
    def tool_results_dir(self) -> Path:
        return self.root / "tool-results"

    @property
    def file_history_dir(self) -> Path:
        return self.root / "file-history"

    @property
    def meta(self) -> Path:
        return self.root / "meta.json"

    def tool_result_path(self, tool_use_id: str) -> Path:
        return self.tool_results_dir / f"{tool_use_id}.txt"

    def file_history_path(self, snapshot_hash: str) -> Path:
        return self.file_history_dir / f"{snapshot_hash}.snap"

    def ensure_dirs(self) -> None:
        """確保所有子目錄存在(idempotent)。"""
        self.root.mkdir(parents=True, exist_ok=True)
        self.tool_results_dir.mkdir(exist_ok=True)
        self.file_history_dir.mkdir(exist_ok=True)


def session_paths(session_id: UUID, root: Path | None = None) -> SessionPaths:
    """取得 SessionPaths。"""
    base = root if root is not None else default_session_root()
    return SessionPaths(
        session_id=session_id,
        root=base / str(session_id),
    )
