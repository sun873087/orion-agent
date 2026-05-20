"""ToolSearchTool。對應 TS ToolSearchTool。

deferred tool 機制:大型工具集(plugin / MCP)展開後可能 100+ 個,
全放 system prompt 會吃 cache budget。改 lazy:

- Tool 有 `should_defer = True` 屬性 → 不放完整 schema 進 system,只列名稱
- 模型呼叫 `ToolSearch({query: "select:NotebookEdit,Bash"})` → 回 JSON Schema 字串
  夾在 `<functions>...</functions>` 內,模型下一輪即可呼叫該工具

支援 query 形式:
- `select:Name1,Name2`(精確選 N 個)
- `keyword`(name + description 模糊搜)
- `+keyword1 keyword2`(全要符合)
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from pydantic import Field

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import TextEvent, Tool, ToolEvent, ToolInput


class ToolSearchInput(ToolInput):
    query: str = Field(
        ...,
        description=(
            "Search query. 'select:Name1,Name2' to load specific tools by name; "
            "or keyword search ('jupyter notebook'); use '+keyword' for required terms."
        ),
    )
    max_results: int = Field(default=5, ge=1, le=20)


class ToolSearchTool:
    name = "ToolSearch"
    description = (
        "Load schemas for deferred tools by name or keyword. "
        "Use this when you need a tool whose schema isn't in your current context."
    )
    input_schema = ToolSearchInput

    def __init__(self, all_tools: list[Tool[Any]] | None = None) -> None:
        self.all_tools = all_tools or []

    def update_tools(self, tools: list[Tool[Any]]) -> None:
        """Conversation 可動態 push 新工具 list 進來(MCP / plugin reload 用)。"""
        self.all_tools = tools

    async def call(
        self,
        input: ToolSearchInput,
        ctx: AgentContext, # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        q = input.query.strip()
        matched: list[Tool[Any]]

        if q.startswith("select:"):
            wanted = {n.strip() for n in q.removeprefix("select:").split(",") if n.strip()}
            matched = [t for t in self.all_tools if t.name in wanted]
        else:
            terms = q.lower().split()
            required: list[str] = []
            preferred: list[str] = []
            for term in terms:
                if term.startswith("+") and len(term) > 1:
                    required.append(term[1:])
                else:
                    preferred.append(term)

            def _matches(tool: Tool[Any]) -> bool:
                blob = (tool.name + " " + (tool.description or "")).lower()
                return all(r in blob for r in required) and (
                    not preferred or any(p in blob for p in preferred)
                )

            matched = [t for t in self.all_tools if _matches(t)]
            matched = matched[: input.max_results]

        if not matched:
            yield TextEvent(text=f"No tools matched query: {q!r}")
            return

        lines: list[str] = ["<functions>"]
        for t in matched:
            try:
                schema = t.input_schema.model_json_schema()
            except Exception: # noqa: BLE001
                schema = {}
            entry = {
                "name": t.name,
                "description": t.description or "",
                "parameters": schema,
            }
            lines.append("<function>" + json.dumps(entry) + "</function>")
        lines.append("</functions>")
        yield TextEvent(text="\n".join(lines))

    def is_concurrency_safe(self, input: ToolSearchInput) -> bool: # noqa: ARG002
        return True

    def is_read_only(self, input: ToolSearchInput) -> bool: # noqa: ARG002
        return True

    def max_result_size_chars(self) -> int | float:
        return 50_000
