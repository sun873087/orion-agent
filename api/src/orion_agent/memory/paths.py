"""Per-user memory 路徑管理。

預設 ~/.orion/users/<user_id>/memory/
  ├─ MEMORY.md          手寫索引(每行 - [Title](file.md) — 一行說明)
  ├─ user_*.md          使用者偏好 / 角色 / 知識
  ├─ feedback_*.md      明確要求記住的指引
  ├─ project_*.md       專案脈絡
  └─ reference_*.md     外部系統指標

可由 ORION_USERS_DIR 環境變數覆蓋根目錄。
ORION_USER_ID 環境變數覆蓋 user_id(CLI 預設 "default")。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def default_users_root() -> Path:
    """根目錄。預設 ~/.orion/users/。"""
    raw = os.environ.get("ORION_USERS_DIR")
    if raw:
        return Path(raw)
    return Path.home() / ".orion" / "users"


def default_user_id() -> str:
    """預設 user id。CLI 模式單 user 用 "default";ORION_USER_ID 可覆蓋。"""
    return os.environ.get("ORION_USER_ID", "default")


@dataclass(frozen=True)
class MemoryPaths:
    """單一 user 的 memory paths。"""

    user_id: str
    root: Path
    """user root(已含 user_id)。"""

    @property
    def memory_dir(self) -> Path:
        return self.root / "memory"

    @property
    def index(self) -> Path:
        return self.memory_dir / "MEMORY.md"

    def memory_file(self, filename: str) -> Path:
        return self.memory_dir / filename

    def ensure_dirs(self) -> None:
        """確保 user dir + memory dir 存在(idempotent)。"""
        self.memory_dir.mkdir(parents=True, exist_ok=True)


def user_memory_paths(
    user_id: str | None = None,
    *,
    users_root: Path | None = None,
) -> MemoryPaths:
    """取 user 的 MemoryPaths。"""
    uid = user_id if user_id is not None else default_user_id()
    base = users_root if users_root is not None else default_users_root()
    return MemoryPaths(user_id=uid, root=base / uid)
