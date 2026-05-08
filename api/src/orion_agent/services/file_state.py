"""File state cache — Phase 12。對應 TS Claude Code `src/utils/fileStateCache.ts`。

用途:Edit / Write 工具強制要求「先 Read 過該檔」,而且讀後檔案沒被外部修改。
否則模型可能基於過時內容做 edit → 資料毀損 / silent overwrite。

設計:
- per-Conversation(放在 AgentContext.file_state_cache)
- 只記 mtime + size — 80/20:常見變動會抓到,輕微 touch 而已可能誤判,但成本極低
- (Phase 12 不算 hash;若 production 證明 mtime/size 不夠精準,Phase 12b 改進)
- 不限制 read 次數,只關心「最後一次 read 後是否被外部改動」
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileSnapshot:
    """Read 當下的檔案快照。"""

    path: Path
    mtime_ns: int
    size: int


class FileStateCache:
    """跨 turn 的 file Read 快取。"""

    def __init__(self) -> None:
        self._snapshots: dict[Path, FileSnapshot] = {}

    @staticmethod
    def _key(path: Path) -> Path:
        """正規化 key(resolve symlinks + 絕對路徑)。

        若 resolve 失敗(檔不存在的情境)就用 absolute() 退而求其次。
        """
        try:
            return path.resolve(strict=False)
        except OSError:
            return path.absolute()

    def record_read(self, path: Path) -> None:
        """FileReadTool 完成讀取後呼叫。

        若檔不存在 → no-op(模型 read 不存在的檔本來就會被工具回 error,
        cache 不需要紀錄)。
        """
        key = self._key(path)
        if not key.exists():
            return
        try:
            stat = key.stat()
        except OSError:
            return
        self._snapshots[key] = FileSnapshot(
            path=key,
            mtime_ns=stat.st_mtime_ns,
            size=stat.st_size,
        )

    def has_been_read(self, path: Path) -> bool:
        return self._key(path) in self._snapshots

    def is_stale(self, path: Path) -> bool:
        """檔案讀過後是否被外部修改?

        - 沒讀過 → True(視為 stale,Edit 必須先 Read)
        - 檔不存在 → True
        - mtime 或 size 變動 → True
        - 都沒變 → False
        """
        key = self._key(path)
        snap = self._snapshots.get(key)
        if snap is None:
            return True
        if not key.exists():
            return True
        try:
            stat = key.stat()
        except OSError:
            return True
        return stat.st_mtime_ns != snap.mtime_ns or stat.st_size != snap.size

    def invalidate(self, path: Path) -> None:
        """主動移除某檔的 snapshot(Edit / Write 完成後 caller 可選擇 invalidate
        以強制下次 Edit 重新 Read,或自己再 record_read 更新)。"""
        self._snapshots.pop(self._key(path), None)

    def __contains__(self, path: object) -> bool:
        if not isinstance(path, Path):
            return False
        return self.has_been_read(path)

    def __len__(self) -> int:
        return len(self._snapshots)


def require_fresh_read(
    cache: FileStateCache | None,
    path: Path,
) -> str | None:
    """便利檢查:Edit / Write 進入前呼叫。

    Returns:
        None — OK,可以動手寫
        str — 該訊息字串就是要回給模型的錯誤(尚未 Read / Read 後被外部改過)
    """
    if cache is None:
        return None  # 沒啟用 cache → 不強制(向後相容)
    if not cache.has_been_read(path):
        return (
            f"Must Read {path} before editing or writing — the model needs to "
            "see the current content first."
        )
    if cache.is_stale(path):
        return (
            f"{path} has been modified externally since you last Read it. "
            "Re-read the file before editing to avoid overwriting changes."
        )
    return None


__all__ = [
    "FileSnapshot",
    "FileStateCache",
    "require_fresh_read",
]
