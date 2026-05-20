"""side_query — 主迴圈中插入小 LLM 呼叫,不汙染主對話。

對應 TS Claude Code `src/utils/sideQuery.ts`。

特性:
  - **不寫 transcript**(主對話 / SessionStorage 完全沒紀錄)
  - **獨立 abort signal**(可被 turn-level abort 取消;不繼承父 abort)
  - **不影響 conversation.stats**(side query 用量另外回給 caller,caller 自行決定計費)
  - **JSON Schema 強制輸出**(用 Anthropic tool_choice 路徑或 OpenAI structured output;
    若 provider 不支援就走純文字 + caller 自行解析)

Caller 範例:
  - `select_relevant_memories`:挑相關 memory 名單(JSON list[str])
  - compaction summary:摘要前段對話
  - title generation / prompt suggestion(預留)

設計上 **不直接呼 anthropic SDK**;改透過 LLMProvider.stream(同 query_loop 用的介面),
換 provider 也能用。沒有 SessionStorage 注入 → 自動不寫 transcript。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

import anyio

from orion_model.events import (
    MessageStopEvent,
    TextDeltaEvent,
    ToolUseStopEvent,
)
from orion_model.provider import LLMProvider
from orion_model.tool_def import ToolDefinition
from orion_model.types import NormalizedMessage

SideQuerySource = Literal[
    "memdir_relevance",
    "compact_summary",
    "title_generation",
    "prompt_suggestion",
    "general",
]
"""side_query 用途分類 — 供 telemetry / debug 區分。"""


@dataclass
class SideQueryParams:
    """side_query 輸入。"""

    system: str
    """完整系統 prompt。**不繼承**主對話的 7 段組裝;由 caller 自帶。"""

    user_text: str
    """單一 user message 內容(side query 通常一次性,不需要多輪歷史)。"""

    max_tokens: int = 256
    """回應上限。memory selector 級別 256 夠,摘要要 1024+。case by case。"""

    json_schema: dict[str, Any] | None = None
    """強制 JSON Schema 輸出;None → 純文字。
    結構:`{"name": "respond", "schema": {...}}` — 內部會包成 tool_use 模式。"""

    query_source: SideQuerySource = "general"
    """供日誌 / metrics tag。"""


@dataclass
class SideQueryUsage:
    """side query 用量。caller 可選擇是否計入 cost tracker。"""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0


@dataclass
class SideQueryResult:
    """side_query 結果。

    text:純文字輸出(無 schema 時)。
    structured:JSON Schema 模式時模型回的 dict;失敗 / 沒 schema 時為 None。
    """

    text: str = ""
    structured: dict[str, Any] | None = None
    usage: SideQueryUsage = field(default_factory=SideQueryUsage)


def _build_schema_tool(schema: dict[str, Any]) -> ToolDefinition:
    """把 JSON Schema 包成假 tool_use 給模型(Anthropic / OpenAI 都吃)。"""
    name = str(schema.get("name") or "respond")
    inner = schema.get("schema")
    if not isinstance(inner, dict):
        inner = schema # caller 直接傳 schema dict 也支援
    return ToolDefinition(
        name=name,
        description="Respond with structured JSON conforming to the provided schema.",
        input_schema=inner,
    )


async def side_query(
    params: SideQueryParams,
    *,
    provider: LLMProvider,
    abort: anyio.Event | None = None,
) -> SideQueryResult:
    """執行 side query。

    Args:
        params: 內容 / 設定。
        provider: 任一 LLMProvider(Anthropic / OpenAI / Mock)。
        abort: 獨立 abort 旗標;若設,stream 中途偵測到會提前停。
            **不繼承** AgentContext.abort_event — caller 想串就明確傳。

    Returns:
        SideQueryResult — text / structured / usage。

    本函式 **不會 raise**(除非 provider.stream 自身 raise,例如 API key 不對)。
    parse 失敗只會回 structured=None,讓 caller 走 fallback。
    """
    user_msg = NormalizedMessage(role="user", content=params.user_text)
    tools: list[ToolDefinition] = []
    schema_tool: ToolDefinition | None = None
    if params.json_schema is not None:
        schema_tool = _build_schema_tool(params.json_schema)
        tools = [schema_tool]

    text_chunks: list[str] = []
    structured_input: dict[str, Any] | None = None
    usage = SideQueryUsage()

    async for ev in provider.stream(
        system=params.system,
        messages=[user_msg],
        tools=tools or None,
        max_tokens=params.max_tokens,
    ):
        if abort is not None and abort.is_set():
            break
        if isinstance(ev, TextDeltaEvent):
            text_chunks.append(ev.text)
        elif isinstance(ev, ToolUseStopEvent):
            if (
                schema_tool is not None
                and ev.tool_name == schema_tool.name
                and isinstance(ev.full_input, dict)
            ):
                structured_input = ev.full_input
        elif isinstance(ev, MessageStopEvent):
            usage.input_tokens = ev.usage.input_tokens
            usage.output_tokens = ev.usage.output_tokens
            usage.cache_read_tokens = ev.usage.cache_read_tokens
            break

    text_out = "".join(text_chunks)

    # JSON Schema 模式但模型沒走 tool_use → 試著從 text fallback 解 JSON
    if structured_input is None and params.json_schema is not None and text_out.strip():
        structured_input = _try_parse_json(text_out)

    return SideQueryResult(text=text_out, structured=structured_input, usage=usage)


def _try_parse_json(text: str) -> dict[str, Any] | None:
    """寬鬆 JSON 解析:整段 / 抓第一個 `{...}` 區塊。

    模型偶爾在 schema 模式下還是回純 JSON 字串(provider 不支援 tool_choice 強制)。
    用這個 fallback 救一下。
    """
    text = text.strip()
    if not text:
        return None
    # 直接 parse
    try:
        v = json.loads(text)
    except json.JSONDecodeError:
        v = None
    if isinstance(v, dict):
        return v
    # 抓第一段 { ... }(naive 但夠用)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            v2 = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
        if isinstance(v2, dict):
            return v2
    return None


__all__ = [
    "SideQueryParams",
    "SideQueryResult",
    "SideQuerySource",
    "SideQueryUsage",
    "side_query",
]
