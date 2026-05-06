"""Normalized 訊息型別。

Phase 1+ 只見這些,看不到 anthropic / openai SDK 細節。
Provider 內部把這些翻譯成各家原生格式。
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class TextBlock(BaseModel):
    """純文字 content block。"""

    type: Literal["text"] = "text"
    text: str


class ToolUseBlock(BaseModel):
    """模型呼叫工具(assistant message 內)。"""

    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, Any]


class ToolResultBlock(BaseModel):
    """工具執行結果(user message 內,回填給模型)。"""

    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str | list[TextBlock | ImageBlock]
    is_error: bool = False


class ImageBlock(BaseModel):
    """圖片(base64-encoded)。"""

    type: Literal["image"] = "image"
    media_type: str  # "image/png" / "image/jpeg" / "image/gif" / "image/webp"
    data: str         # base64-encoded


class ThinkingBlock(BaseModel):
    """推理區塊。Anthropic extended thinking + OpenAI o-series reasoning 共用。"""

    type: Literal["thinking"] = "thinking"
    text: str


ContentBlock = Annotated[
    TextBlock | ToolUseBlock | ToolResultBlock | ImageBlock | ThinkingBlock,
    Field(discriminator="type"),
]


class NormalizedMessage(BaseModel):
    """單一訊息(user / assistant / system)。

    content 可以是 str(簡單 text)或 list[ContentBlock](複雜 — 含工具 / 圖片等)。
    """

    role: Literal["user", "assistant", "system"]
    content: str | list[ContentBlock]
