"""File upload store。

取代 TS `@file` ref。前端用 multipart upload 把檔案存到 per-user upload dir,
agent 用 `read_upload(upload_id)` 取內容,或將 upload_id 當成 user message attachment 引用。

設計:
- Canonical per-user 目錄:`~/.orion/users/<user_id>/uploads/<upload_id>.<ext>`
  與 memory(`users/<user_id>/memory/`)同層,「per-user 跨 session 資料一律歸 users/」。
- Legacy fallback:`~/.orion/uploads/<user_id>/<upload_id>.<ext>`(起初寫進這裡)
  寫入只走新路徑;讀 / 列 / 刪會 union 新+舊,保護既有本機資料,不強迫一次 migrate。
- upload_id = uuid hex[:16](短足以識別,不會碰撞 in-session)
- 大檔限制 10 MB(超過拒絕,避免 disk 爆)
- read_upload 回 bytes;`read_upload_text` 回 str(UTF-8 decode 失敗 raise)
- 過期清理留(目前不自動清)

存儲根目錄可由 `ORION_HOME` 覆蓋(對應 ConfigTool 同 env)。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

_DEFAULT_MAX_BYTES = 10 * 1024 * 1024 # 10 MB
_UPLOAD_ID_PATTERN = re.compile(r"^[a-f0-9]{8,32}$")


class UploadTooLargeError(ValueError):
    """超過 size limit。"""


class UploadNotFoundError(FileNotFoundError):
    """指定 upload_id 不存在。"""


def _orion_base() -> Path:
    return Path(os.environ.get("ORION_HOME") or str(Path.home() / ".orion"))


def _user_uploads_dir(user_id: str) -> Path:
    """Canonical 新路徑:`<base>/users/<user_id>/uploads/`。寫入永遠走這。"""
    return _orion_base() / "users" / user_id / "uploads"


def _legacy_user_uploads_dir(user_id: str) -> Path:
    """Legacy 舊路徑:`<base>/uploads/<user_id>/`。起初使用,僅 read fallback。

    之後 refactor 走新路徑(users/<user_id>/uploads/)以與 memory 對齊。
    既有本機資料留在舊位置仍可讀,新寫一律新路徑。
    """
    return _orion_base() / "uploads" / user_id


def _candidate_dirs(user_id: str) -> list[Path]:
    """讀 / 列 / 刪要掃的所有路徑(新優先)。"""
    return [_user_uploads_dir(user_id), _legacy_user_uploads_dir(user_id)]


@dataclass
class UploadRecord:
    """已存的上傳檔。"""

    upload_id: str
    user_id: str
    filename: str
    """原始檔名(safe-quoted,只用於顯示)。"""

    path: Path
    """sanitized disk path。"""

    size: int


def _sanitize_filename(name: str) -> str:
    """擋 path traversal — 只留 basename + 安全字元。"""
    # 取 basename(防 ../../ 之類)
    base = os.path.basename(name) or "upload"
    # 限定字元集:字母 / 數字 / .-_
    cleaned = re.sub(r"[^A-Za-z0-9.\-_]", "_", base)
    return cleaned[:128] or "upload"


def save_upload(
    *,
    user_id: str,
    filename: str,
    data: bytes,
    max_bytes: int = _DEFAULT_MAX_BYTES,
) -> UploadRecord:
    """存一個檔案。回 UploadRecord(含 upload_id)。"""
    if not user_id:
        raise ValueError("user_id required")
    if len(data) > max_bytes:
        raise UploadTooLargeError(
            f"upload is {len(data)} bytes, exceeds {max_bytes} bytes limit",
        )

    upload_id = uuid4().hex[:16]
    safe_name = _sanitize_filename(filename)
    suffix = Path(safe_name).suffix or ""
    target_dir = _user_uploads_dir(user_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{upload_id}{suffix}"
    target_path.write_bytes(data)

    return UploadRecord(
        upload_id=upload_id,
        user_id=user_id,
        filename=safe_name,
        path=target_path,
        size=len(data),
    )


def _resolve_path(user_id: str, upload_id: str) -> Path:
    """新路徑找不到時 fallback 到 legacy 舊路徑。"""
    if not _UPLOAD_ID_PATTERN.match(upload_id):
        raise UploadNotFoundError(f"invalid upload_id: {upload_id!r}")
    for target_dir in _candidate_dirs(user_id):
        if not target_dir.exists():
            continue
        matches = list(target_dir.glob(f"{upload_id}*"))
        if not matches:
            continue
        # 找精確 prefix 配對(`<id>.ext` 或 `<id>` 無 ext)
        for p in matches:
            if p.name == upload_id or p.stem == upload_id:
                return p
        return matches[0]
    raise UploadNotFoundError(f"upload not found: {upload_id}")


def read_upload(user_id: str, upload_id: str) -> bytes:
    """讀檔回 bytes。upload_id 不存在 → UploadNotFoundError。"""
    return _resolve_path(user_id, upload_id).read_bytes()


def read_upload_text(user_id: str, upload_id: str) -> str:
    """讀檔回 UTF-8 字串。失敗 raise UnicodeDecodeError。"""
    return _resolve_path(user_id, upload_id).read_text(encoding="utf-8")


def delete_upload(user_id: str, upload_id: str) -> bool:
    """刪除單一上傳檔。Returns True 若存在並刪除。"""
    try:
        path = _resolve_path(user_id, upload_id)
    except UploadNotFoundError:
        return False
    path.unlink()
    return True


def list_uploads(user_id: str) -> list[UploadRecord]:
    """列 user 所有 upload 檔(metadata 從 disk 重建,filename 已 sanitize)。

    Union 新路徑與 legacy 舊路徑;同 upload_id 兩處都有以新路徑為準。
    """
    out: list[UploadRecord] = []
    seen: set[str] = set()
    for target_dir in _candidate_dirs(user_id):
        if not target_dir.exists():
            continue
        for p in sorted(target_dir.iterdir()):
            if not p.is_file():
                continue
            # 嘗試 parse upload_id(stem 至少 8 字 hex)
            stem = p.stem
            if not _UPLOAD_ID_PATTERN.match(stem):
                continue
            if stem in seen:
                continue # 新路徑優先(_candidate_dirs 順序保證)
            try:
                size = p.stat().st_size
            except OSError:
                continue
            seen.add(stem)
            out.append(
                UploadRecord(
                    upload_id=stem,
                    user_id=user_id,
                    filename=p.name,
                    path=p,
                    size=size,
                ),
            )
    return out
