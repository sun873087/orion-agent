"""Normalized 訊息型別。

+ 只見這些,看不到 anthropic / openai SDK 細節。
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
    thought_signature: str | None = None
    """Gemini native API 跨 turn thinking 狀態:Gemini 2.5+ thinking model
    生 function_call 時會附 base64 signature,user 下次帶 functionResponse
    回去時 Gemini 期待 echo 同支 signature。其他 provider 忽略。"""


class ToolResultBlock(BaseModel):
    """工具執行結果(user message 內,回填給模型)。"""

    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str | list[TextBlock | ImageBlock]
    is_error: bool = False


class ImageBlock(BaseModel):
    """圖片(base64-encoded)。"""

    type: Literal["image"] = "image"
    media_type: str # "image/png" / "image/jpeg" / "image/gif" / "image/webp"
    data: str # base64-encoded


class ThinkingBlock(BaseModel):
    """推理區塊。Anthropic extended thinking + OpenAI o-series reasoning 共用。"""

    type: Literal["thinking"] = "thinking"
    text: str


class TombstoneBlock(BaseModel):
    """被 autoCompact 替換掉的訊息範圍 placeholder。

    送給模型看的時候只是一段 "summary" text。內部保留 range_start_uuid /
    range_end_uuid 給 resume 對齊用 — 萬一兩個 conversation 共用 transcript,
    或要做 audit / replay。
    """

    type: Literal["tombstone"] = "tombstone"
    summary: str
    """送給模型看的摘要(LLM 生成)。"""

    range_start_msg_index: int
    """被替換的 message 範圍起始 index(原 state_messages 的)。"""

    range_end_msg_index: int
    """被替換的 message 範圍結束 index(inclusive)。"""

    original_token_count: int
    """被壓縮前的概略 token 數(供 telemetry / debug)。"""

    captured_at: str
    """ISO datetime,壓縮發生時間。"""


ContentBlock = Annotated[
    TextBlock | ToolUseBlock | ToolResultBlock | ImageBlock | ThinkingBlock | TombstoneBlock,
    Field(discriminator="type"),
]


class NormalizedMessage(BaseModel):
    """單一訊息(user / assistant / system)。

    content 可以是 str(簡單 text)或 list[ContentBlock](複雜 — 含工具 / 圖片等)。
    """

    role: Literal["user", "assistant", "system"]
    content: str | list[ContentBlock]
