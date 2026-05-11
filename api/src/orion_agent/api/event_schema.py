"""WebSocket event schema(雙向)。

對應 spec § 5 event_schema.py。

兩個 union:
- `ClientEvent`(client → server):user 訊息、permission decision、abort
- `ServerEvent`(server → client):assistant text/thinking、tool 進度、permission ask、turn 完成、loop 終止、error

每個 event 有 `type` literal 作 discriminator,Pydantic 自動 validate。

WebSocket 一條訊息 = 一個 JSON object,直接 model_dump_json() / model_validate_json()。
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

# ─── Client → Server ────────────────────────────────────────────────────────


class UserMessageEvent(BaseModel):
    type: Literal["user_message"] = "user_message"
    content: str


class PermissionDecisionEvent(BaseModel):
    type: Literal["permission_decision"] = "permission_decision"
    request_id: str
    decision: Literal["allow", "always_allow", "deny"]


class AbortEvent(BaseModel):
    type: Literal["abort"] = "abort"


class AskUserAnswerEvent(BaseModel):
    """client 回覆 server 的 AskUserQuestionAskEvent。

    `answers` 是 question text → 使用者選的 label(或開放式回答的純文字)。
    若使用者放棄/超時,client 可送 `answers={}` 提早通知。
    """

    type: Literal["ask_user_answer"] = "ask_user_answer"
    request_id: str
    answers: dict[str, str]


ClientEvent = Annotated[
    UserMessageEvent | PermissionDecisionEvent | AbortEvent | AskUserAnswerEvent,
    Field(discriminator="type"),
]


# ─── Server → Client ────────────────────────────────────────────────────────


class UserTextEvent(BaseModel):
    """重播歷史時用 — server 送 user 過去說過的訊息給 client 顯示(client 自己送的不會收到回送)。"""

    type: Literal["user_text"] = "user_text"
    text: str


class HistoryReplayDoneEvent(BaseModel):
    """歷史重播完成標記 — client 用來 flush 任何 pending streaming state。"""

    type: Literal["history_replay_done"] = "history_replay_done"


class AssistantTextEvent(BaseModel):
    """模型 streaming 文字增量。"""

    type: Literal["assistant_text"] = "assistant_text"
    text: str


class AssistantThinkingEvent(BaseModel):
    """模型 reasoning(extended thinking)增量。"""

    type: Literal["assistant_thinking"] = "assistant_thinking"
    text: str


class ToolUseEvent(BaseModel):
    """工具 call 開始。"""

    type: Literal["tool_use"] = "tool_use"
    tool_use_id: str
    tool_name: str
    input: dict[str, Any]


class ToolResultEvent(BaseModel):
    """工具 call 結束 + 結果摘要。"""

    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    tool_name: str
    content: str
    is_error: bool = False


class PermissionAskEvent(BaseModel):
    """server 反問 user 是否允許工具執行。client 必須 reply PermissionDecisionEvent。"""

    type: Literal["permission_ask"] = "permission_ask"
    request_id: str
    tool_name: str
    input: dict[str, Any]
    timeout_seconds: int = 60


class AskUserQuestionAskEvent(BaseModel):
    """server 反問 user 一/多題(來自 AskUserQuestion tool)。

    `questions` 是 AskQuestion.model_dump() 的 list:每題含 question / header /
    options(label+description)/ multi_select。client 必須 reply
    AskUserAnswerEvent(同 request_id)。
    """

    type: Literal["ask_user_question"] = "ask_user_question"
    request_id: str
    questions: list[dict[str, Any]]
    timeout_seconds: int = 300


class TurnCompleteEvent(BaseModel):
    """assistant 一輪結束(streaming text + tool_use blocks 收齊)。"""

    type: Literal["turn_complete"] = "turn_complete"
    stop_reason: str
    input_tokens: int
    output_tokens: int


class TerminalEvent(BaseModel):
    """整個 query_loop 結束(所有 turn 都做完)。"""

    type: Literal["terminal"] = "terminal"
    reason: str
    total_turns: int


class ErrorEvent(BaseModel):
    """通用 error(server 端 exception / unauthorized / etc.)。"""

    type: Literal["error"] = "error"
    message: str


ServerEvent = Annotated[
    UserTextEvent
    | HistoryReplayDoneEvent
    | AssistantTextEvent
    | AssistantThinkingEvent
    | ToolUseEvent
    | ToolResultEvent
    | PermissionAskEvent
    | AskUserQuestionAskEvent
    | TurnCompleteEvent
    | TerminalEvent
    | ErrorEvent,
    Field(discriminator="type"),
]


# ─── 輔助 wrapper(parse 用) ─────────────────────────────────────────────────


class _ClientEventEnvelope(BaseModel):
    event: ClientEvent


def parse_client_event(raw: dict[str, Any]) -> ClientEvent:
    """把 client 送來的 raw dict 解成 ClientEvent。

    Pydantic discriminated union 對 top-level dict 的處理需要包個 wrapper,
    或直接 model_validate 各 type — 此處採用後者(更簡單)。
    """
    type_str = raw.get("type")
    if type_str == "user_message":
        return UserMessageEvent.model_validate(raw)
    if type_str == "permission_decision":
        return PermissionDecisionEvent.model_validate(raw)
    if type_str == "abort":
        return AbortEvent.model_validate(raw)
    if type_str == "ask_user_answer":
        return AskUserAnswerEvent.model_validate(raw)
    raise ValueError(f"Unknown client event type: {type_str!r}")


def serialize_server_event(event: ServerEvent | BaseModel) -> dict[str, Any]:
    """server event → dict,可直接 ws.send_json 出去。"""
    return event.model_dump(mode="json", exclude_none=True)
