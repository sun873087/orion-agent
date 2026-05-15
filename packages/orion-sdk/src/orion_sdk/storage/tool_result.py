"""Tool result 第 2 層持久化:大結果寫檔 + 替換成 preview。

對應 TS Claude Code `src/utils/toolResultStorage.ts`。

設計:
- 工具產出 text < 100KB → 不處理(原樣回填)
- 工具產出 text >= 100KB → 寫到 ~/.orion/sessions/<sid>/tool-results/<tool_use_id>.txt,
  回填內容換成 preview(前 2KB)+ 包標籤 + 路徑
- 空字串 → 替換成 "(tool produced no output)"
- 後續 phase 3(budget aggregation)在此之上,決定哪些 ToolResult 進一步替換

使用方式:`maybe_persist_large_tool_result(...)` 回傳「應送給模型的 content 字串」。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from orion_sdk.storage.paths import session_paths

LARGE_THRESHOLD_BYTES = 100 * 1024
"""超過此 byte 數就持久化。對應 TS LARGE_TOOL_RESULT_THRESHOLD。"""

PREVIEW_MAX_CHARS = 2048
"""寫入後留給模型看的 preview 大小。"""


@dataclass(frozen=True)
class PersistedResult:
    """maybe_persist 的詳細回傳。caller 通常只需要 .content_for_model。"""

    content_for_model: str
    """要塞進 ToolResultBlock.content 的字串(可能是原文 / preview / "(no output)")。"""

    persisted_path: Path | None = None
    """若有持久化,檔案路徑;否則 None。"""

    persisted_size: int = 0
    """持久化的 byte 數,沒持久化為 0。"""


def generate_preview(content: str, max_chars: int = PREVIEW_MAX_CHARS) -> str:
    """裁前 max_chars 字,加 truncate 註記。"""
    if len(content) <= max_chars:
        return content
    head = content[:max_chars]
    return head + f"\n... [{len(content) - max_chars} more chars truncated, see persisted file]"


def build_large_result_envelope(
    tool_use_id: str,
    preview: str,
    persisted_path: Path,
    full_size: int,
) -> str:
    """打包 preview + 路徑成模型友善的訊息。"""
    return (
        f"<persisted-output tool_use_id={tool_use_id!r} "
        f"path={str(persisted_path)!r} size={full_size}>\n"
        f"{preview}\n"
        f"</persisted-output>"
    )


def persist_tool_result(
    session_id: UUID,
    tool_use_id: str,
    content: str,
) -> Path:
    """寫到 session 的 tool-results/<id>.txt。確保 dir 存在。"""
    sp = session_paths(session_id)
    sp.ensure_dirs()
    path = sp.tool_result_path(tool_use_id)
    path.write_text(content, encoding="utf-8")
    return path


def maybe_persist_large_tool_result(
    session_id: UUID,
    tool_use_id: str,
    content: str,
    *,
    threshold: int = LARGE_THRESHOLD_BYTES,
) -> PersistedResult:
    """**主入口**。tool_execution 在 build ToolResultBlock 前 call 此 function。

    Args:
        session_id: 用以推算 sessions/<id>/tool-results/ 路徑
        tool_use_id: 模型 emit 的 tool_use id,作為檔名
        content: tool 產出的純文字
        threshold: 超過幾 bytes 才持久化(預設 100KB)

    Returns:
        PersistedResult,caller 用 .content_for_model 塞進 ToolResultBlock。
    """
    if not content:
        return PersistedResult(content_for_model="(tool produced no output)")

    size = len(content.encode("utf-8"))
    if size <= threshold:
        return PersistedResult(content_for_model=content)

    path = persist_tool_result(session_id, tool_use_id, content)
    preview = generate_preview(content)
    envelope = build_large_result_envelope(tool_use_id, preview, path, size)
    return PersistedResult(
        content_for_model=envelope,
        persisted_path=path,
        persisted_size=size,
    )
