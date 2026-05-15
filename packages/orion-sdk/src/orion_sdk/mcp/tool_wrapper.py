"""把 MCP tool dict 動態包成 Phase 1 的 Tool Protocol。

對應 spec § 5 tool_wrapper.py。

從 MCP server 拿到的 tool 定義長這樣:
```python
{
  "name": "read_file",
  "description": "Read a file from disk",
  "inputSchema": {"type": "object", "properties": {...}, "required": [...]},
  "annotations": {
    "readOnlyHint": True,        # → is_concurrency_safe = True
    "destructiveHint": False,    # → is_concurrency_safe = False(若 True)
    "openWorldHint": False,
  }
}
```

包裝後產出符合 `core.tool.Tool` Protocol 的物件,可加進 Conversation.tools。

命名:`mcp__<server>__<tool_name>`(spec 約定,避開既有工具)。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput
from orion_sdk.mcp.schema_to_pydantic import schema_to_pydantic_model

if TYPE_CHECKING:
    from orion_sdk.mcp.client import McpClient


def _qualified_tool_name(server_name: str, tool_name: str) -> str:
    """`mcp__<server>__<tool>` — 避開內建工具命名。"""
    return f"mcp__{server_name}__{tool_name}"


class McpToolWrapper:
    """把 MCP tool 包成 Phase 1 Tool Protocol。

    動態 attribute 設定:name / description / input_schema / call。
    `is_concurrency_safe` 從 annotations 推。
    """

    def __init__(
        self,
        *,
        server_name: str,
        tool_name: str,
        description: str,
        input_schema: dict[str, Any],
        annotations: dict[str, Any] | None,
        client: McpClient,
    ) -> None:
        self.name = _qualified_tool_name(server_name, tool_name)
        self.description = (description or "").strip() or f"MCP tool {tool_name!r}"
        self._server_name = server_name
        self._raw_tool_name = tool_name
        self._client = client
        self._annotations = annotations or {}

        # 動態建 Pydantic model
        self.input_schema = schema_to_pydantic_model(
            input_schema,
            model_name=f"McpInput_{server_name}_{tool_name}",
        )

    async def call(
        self,
        input: ToolInput,
        ctx: AgentContext,  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        """呼 MCP server 的 tool。"""
        try:
            args = input.model_dump(exclude_none=True)
        except Exception as e:  # noqa: BLE001
            yield ErrorEvent(message=f"failed to serialize input: {e}")
            return

        try:
            result = await self._client.call_tool(self._raw_tool_name, args)
        except Exception as e:  # noqa: BLE001 — server 錯不該炸 conversation
            yield ErrorEvent(
                message=(
                    f"MCP server {self._server_name!r} call_tool({self._raw_tool_name!r}) "
                    f"failed: {type(e).__name__}: {e}"
                )
            )
            return

        # MCP result 通常是 dict with content list of {type: text|image, text: ...}
        text_chunks: list[str] = []
        is_error = bool(result.get("isError")) if isinstance(result, dict) else False

        content = result.get("content", []) if isinstance(result, dict) else []
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                ctype = item.get("type")
                if ctype == "text":
                    t = item.get("text", "")
                    if isinstance(t, str):
                        text_chunks.append(t)
                # image / resource — Phase 5 不展開,只記 stub
                elif ctype in ("image", "resource"):
                    text_chunks.append(
                        f"[{ctype} content elided — Phase 5 不展開,Phase 10 處理]"
                    )

        if not text_chunks:
            # 沒 content 給 raw JSON 也比啥都不給好
            text_chunks.append(json.dumps(result, ensure_ascii=False)[:5000])

        joined = "\n".join(text_chunks)
        if is_error:
            yield ErrorEvent(message=joined)
        else:
            yield TextEvent(text=joined)

    def is_concurrency_safe(self, input: Any) -> bool:  # noqa: ARG002
        """從 annotations 推:readOnlyHint=True 且非 destructive → safe;否則 unsafe。"""
        if self._annotations.get("destructiveHint") is True:
            return False
        return self._annotations.get("readOnlyHint") is True

    def is_read_only(self, input: Any) -> bool:  # noqa: ARG002
        return bool(self._annotations.get("readOnlyHint"))

    def max_result_size_chars(self) -> int | float:
        # MCP 大結果由 large_output 處理,這裡給 25K * 4 = 100KB ballpark
        return 100_000


def wrap_mcp_tool(
    *,
    server_name: str,
    tool_def: dict[str, Any],
    client: McpClient,
) -> McpToolWrapper:
    """便利工廠 — 從 MCP server 回的 tool dict 建 wrapper。"""
    return McpToolWrapper(
        server_name=server_name,
        tool_name=tool_def.get("name", "unknown"),
        description=tool_def.get("description", ""),
        input_schema=tool_def.get("inputSchema", {}),
        annotations=tool_def.get("annotations"),
        client=client,
    )
