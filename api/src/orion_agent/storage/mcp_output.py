"""MCP binary output storage — Phase 5 接 Phase 2 stub。

對應 TS Claude Code `src/utils/mcpOutputStorage.ts`。

主要處理 binary(image / pdf / file)。Text 大結果走 mcp/large_output.py。
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from orion_agent.storage.paths import session_paths


def _binary_dir(session_id: UUID) -> Path:
    """每 session 的 binary 持久化路徑。"""
    sp = session_paths(session_id)
    sp.ensure_dirs()
    target = sp.root / "mcp-binaries"
    target.mkdir(exist_ok=True)
    return target


def persist_mcp_binary(
    session_id: UUID,
    tool_use_id: str,
    media_type: str,
    data: bytes,
) -> Path:
    """寫 binary 到 disk,回 path。

    搭配 metadata sidecar(.meta.json)記 media_type / 寫入時間。
    """
    base = _binary_dir(session_id)
    safe_tu = "".join(c if c.isalnum() or c in "-_" else "_" for c in tool_use_id)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    ext = _ext_for_media_type(media_type)
    bin_path = base / f"{safe_tu}-{ts}{ext}"
    bin_path.write_bytes(data)

    meta_path = bin_path.with_suffix(bin_path.suffix + ".meta.json")
    meta_path.write_text(
        json.dumps(
            {
                "tool_use_id": tool_use_id,
                "media_type": media_type,
                "size": len(data),
                "captured_at": datetime.now(UTC).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return bin_path


def load_mcp_binary(
    session_id: UUID,
    tool_use_id: str,
) -> dict[str, Any] | None:
    """根據 tool_use_id 找最早 / 唯一的 binary 檔。

    Returns:
        {"path": Path, "media_type": str, "size": int} 或 None
    """
    base = _binary_dir(session_id)
    safe_tu = "".join(c if c.isalnum() or c in "-_" else "_" for c in tool_use_id)
    candidates = sorted(base.glob(f"{safe_tu}-*"))
    bin_files = [p for p in candidates if not p.name.endswith(".meta.json")]
    if not bin_files:
        return None
    bin_path = bin_files[0]
    meta_path = bin_path.with_suffix(bin_path.suffix + ".meta.json")
    if not meta_path.exists():
        return {
            "path": bin_path,
            "media_type": "application/octet-stream",
            "size": bin_path.stat().st_size,
        }
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        meta = {}
    return {
        "path": bin_path,
        "media_type": meta.get("media_type", "application/octet-stream"),
        "size": bin_path.stat().st_size,
    }


def _ext_for_media_type(media_type: str) -> str:
    mapping = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "application/pdf": ".pdf",
        "application/json": ".json",
        "text/plain": ".txt",
    }
    return mapping.get(media_type, ".bin")


def decode_b64(data: str) -> bytes:
    """base64 string → bytes。"""
    return base64.b64decode(data)
