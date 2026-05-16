"""Filesystem-backed blob store。

Cowork single-user 桌機 app,blob 直接落 ~/.orion-cowork/blobs/<uuid>.bin —
raw bytes,**不** base64。SQLite messages.content_json 內 image 只留 blob_id
ref(`{type: image, media_type, blob_id}`),讓 row 從 MB 縮回 bytes,切歷史對話
不再被 SELECT 撈出來的整段 base64 拖住。

Chat-api / CLI 未來要做同件事時,可把這個 module promote 到 orion-sdk,
傳入不同 root 即可。
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4


class BlobStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, data: bytes) -> str:
        """寫 raw bytes,回 blob_id(uuid4)。"""
        blob_id = str(uuid4())
        path = self.root / f"{blob_id}.bin"
        path.write_bytes(data)
        return blob_id

    def get(self, blob_id: str) -> bytes:
        """讀 raw bytes;blob 不存在丟 FileNotFoundError。"""
        path = self.root / f"{blob_id}.bin"
        return path.read_bytes()

    def has(self, blob_id: str) -> bool:
        return (self.root / f"{blob_id}.bin").exists()

    def delete(self, blob_id: str) -> bool:
        path = self.root / f"{blob_id}.bin"
        if path.exists():
            path.unlink()
            return True
        return False
