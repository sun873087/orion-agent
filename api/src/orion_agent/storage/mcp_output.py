"""MCP output storage — Phase 5 才會用,本檔目前只是 stub。

對應 TS Claude Code `src/utils/mcpOutputStorage.ts`。

Phase 5 將實作:
- binary 結果(image / pdf / file)持久化到 mcp-outputs/
- 大 text 結果走第 2 層 tool_result.py 即可,本檔只處理 binary
- resume 時連同重建

Phase 2 範圍內留空,確保 import 不爆。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID


def persist_mcp_binary(
    session_id: UUID,  # noqa: ARG001
    tool_use_id: str,  # noqa: ARG001
    media_type: str,  # noqa: ARG001
    data: bytes,  # noqa: ARG001
) -> Path | None:
    """Phase 5 才實作。目前回 None。"""
    return None


def load_mcp_binary(
    session_id: UUID,  # noqa: ARG001
    tool_use_id: str,  # noqa: ARG001
) -> dict[str, Any] | None:
    """Phase 5 才實作。"""
    return None
