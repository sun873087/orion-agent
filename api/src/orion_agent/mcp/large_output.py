"""MCP 大結果處理 — 25K token 門檻持久化。

對應 spec § 5 large_output.py + 接 Phase 2 storage/mcp_output stub。

Phase 2 第 2 層 tool_result.py 處理一般工具的 100KB 門檻。MCP 結果常含結構化
schema(JSON 序列化保留 type / nested 資訊),門檻可寬一些 — 用 25K token
(~100KB chars)為 Phase 5 spec 約定值。

流程:
- result < threshold → 原樣回(text 化或 JSON dump)
- result ≥ threshold → 寫 JSON 到 ~/.orion/sessions/<sid>/tool-results/mcp-<server>-<tool>-<ts>.json
  + 回模型 preview(2KB)+ schema hint + jq 範例
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from orion_agent.storage.paths import session_paths

MCP_LARGE_THRESHOLD_BYTES = 25_000 * 4  # ~25K tokens × 4 chars/token = 100KB
"""MCP 結果超過此 byte 數就持久化。"""

MCP_PREVIEW_MAX_CHARS = 2048


@dataclass(frozen=True)
class McpPersistedResult:
    """process_mcp_result 的詳細回傳。"""

    content_for_model: str
    persisted_path: Path | None = None
    persisted_size: int = 0


def _serialize_mcp_result(raw: Any) -> str:
    """MCP result(可能是 dict / list / str / mcp 物件)→ 可寫 disk 的 string。"""
    if isinstance(raw, str):
        return raw
    try:
        return json.dumps(raw, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        return str(raw)


def process_mcp_result(
    *,
    session_id: UUID,
    server_name: str,
    tool_name: str,
    raw_result: Any,
    threshold_bytes: int = MCP_LARGE_THRESHOLD_BYTES,
) -> McpPersistedResult:
    """主入口。Caller 拿到 MCP result 後 call 一次。

    Returns:
        McpPersistedResult,caller 用 .content_for_model 給模型看。
    """
    serialized = _serialize_mcp_result(raw_result)
    size = len(serialized.encode("utf-8"))

    if size <= threshold_bytes:
        return McpPersistedResult(content_for_model=serialized)

    sp = session_paths(session_id)
    sp.ensure_dirs()
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    safe_server = "".join(c if c.isalnum() or c in "-_" else "_" for c in server_name)
    safe_tool = "".join(c if c.isalnum() or c in "-_" else "_" for c in tool_name)
    filename = f"mcp-{safe_server}-{safe_tool}-{ts}.json"
    path = sp.tool_results_dir / filename
    try:
        path.write_text(serialized, encoding="utf-8")
    except OSError:
        # 寫檔失敗 — 仍回原 serialized,讓上層自行截斷
        return McpPersistedResult(content_for_model=serialized[: threshold_bytes])

    preview = serialized[:MCP_PREVIEW_MAX_CHARS]
    if len(serialized) > MCP_PREVIEW_MAX_CHARS:
        preview += f"\n... [{len(serialized) - MCP_PREVIEW_MAX_CHARS} more chars truncated]"

    envelope = (
        f"<persisted-mcp-output server={server_name!r} tool={tool_name!r} "
        f"path={str(path)!r} size={size} bytes>\n"
        f"{preview}\n"
        f"\n"
        f"# To inspect the full result:\n"
        f"#   Use Read or Bash to access {path}\n"
        f"#   Try: jq '.content[0].text' {path}\n"
        f"</persisted-mcp-output>"
    )

    return McpPersistedResult(
        content_for_model=envelope,
        persisted_path=path,
        persisted_size=size,
    )
