"""Streaming events。query_loop 接收這些 normalized event。

Provider 把 anthropic / openai 的原始 streaming events 翻譯成這些。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


@dataclass
class NormalizedUsage:
    """Token 用量(整次 message 累計)。"""

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    reasoning_tokens: int = 0 # OpenAI o-series / GPT-5 的 reasoning


class MessageStartEvent(BaseModel):
    """API 回應開始。"""

    type: Literal["message_start"] = "message_start"
    message_id: str
    model: str


class TextDeltaEvent(BaseModel):
    """模型逐字輸出。"""

    type: Literal["text_delta"] = "text_delta"
    text: str


class ThinkingDeltaEvent(BaseModel):
    """Reasoning / extended thinking 內容(若 model 支援)。"""

    type: Literal["thinking_delta"] = "thinking_delta"
    text: str


class ToolUseStartEvent(BaseModel):
    """模型開始 yield 一個 tool_use block。"""

    type: Literal["tool_use_start"] = "tool_use_start"
    block_index: int
    tool_use_id: str
    tool_name: str


class ToolUseInputDeltaEvent(BaseModel):
    """tool_use 的 input(JSON 增量)。

    完整 input 在 ToolUseStopEvent.full_input 中提供 — 中間的 partial JSON
    可能無效,只 expose 給需要逐字渲染的 UI 用。
    """

    type: Literal["tool_use_input_delta"] = "tool_use_input_delta"
    block_index: int
    partial_json: str


class ToolUseStopEvent(BaseModel):
    """tool_use block 結束(完整 input 已就緒,可拿去執行)。"""

    type: Literal["tool_use_stop"] = "tool_use_stop"
    block_index: int
    tool_use_id: str
    tool_name: str
    full_input: dict[str, Any]


class MessageStopEvent(BaseModel):
    """整個 message 結束。"""

    type: Literal["message_stop"] = "message_stop"
    stop_reason: Literal[
        "end_turn",
        "max_tokens",
        "stop_sequence",
        "tool_use",
        "content_filter",
        "error",
    ]
    usage: NormalizedUsage


NormalizedEvent = Annotated[
    MessageStartEvent
    | TextDeltaEvent
    | ThinkingDeltaEvent
    | ToolUseStartEvent
    | ToolUseInputDeltaEvent
    | ToolUseStopEvent
    | MessageStopEvent,
    Field(discriminator="type"),
]
