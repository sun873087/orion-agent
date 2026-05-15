"""中性 Tool 定義 — 各 provider 自己翻譯成 Anthropic / OpenAI 格式。

與 core.tool.Tool 不同 — Tool 是執行端;ToolDefinition 是「給模型看的版本」。
從 Tool 產生:
  td = ToolDefinition(
      name=my_tool.name,
      description=my_tool.description,
      input_schema=my_tool.input_schema.model_json_schema(),
  )
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ToolDefinition(BaseModel):
    """送給模型看的工具定義(name + description + input JSON Schema)。"""

    name: str
    description: str
    input_schema: dict[str, Any]
    """JSON Schema(由 Pydantic.model_json_schema() 產生)。"""

    cache_control: bool = False
    """是否要在這個 tool 後標 cache breakpoint(Anthropic only,OpenAI 忽略)。"""
