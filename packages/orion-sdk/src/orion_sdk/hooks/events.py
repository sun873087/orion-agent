"""Hook event 型別 + 完整 8 種。

用 dataclass 提供 PreToolUseEvent / PostToolUseEvent(in-process callback,
帶 Tool / AgentContext object reference)。補齊另 6 種 event,並提供
serializable 視圖(`.to_serializable()`)給 settings.json shell hook / webhook 用。

事件清單:
1. PreToolUseEvent 工具執行前(可阻擋 / 改 input)
2. PostToolUseEvent 工具執行成功後(read-only)
3. PostToolUseFailureEvent 工具執行失敗
4. UserPromptSubmitEvent 使用者送入新 prompt
5. SessionStartEvent Conversation 建立 / resume
6. SetupEvent app lifespan startup(只觸發一次)
7. SubagentStartEvent AgentTool 開子 agent
8. FileChangedEvent FileWrite / FileEdit 改檔成功

每個 event 有 `.to_serializable() -> dict` 把 in-process object refs 拿掉,
留純 JSON-serializable 欄位給 shell hook / webhook 用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

if TYPE_CHECKING:
    from orion_sdk.core.state import AgentContext
    from orion_sdk.core.tool import Tool


# ─── events ─────────────────────────────────────────────────────────


@dataclass
class PreToolUseEvent:
    """工具執行前。Hook 可:
    - 回 None / True → 放行
    - 回 False → 視同 permission deny
    - raise → 中斷 query_loop

   :加 session_id / user_id / tool_name / tool_use_id 給 settings hook 用。
    """

    type: Literal["PreToolUse"] = "PreToolUse"
    tool: Tool[Any] | None = None
    tool_input: dict[str, Any] | None = None
    ctx: AgentContext | None = None

    # 加,給 serializable 用
    session_id: str | None = None
    user_id: str | None = None
    tool_name: str | None = None
    tool_use_id: str | None = None

    def to_serializable(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "tool_name": self.tool_name or (self.tool.name if self.tool else None),
            "tool_use_id": self.tool_use_id,
            "tool_input": self.tool_input,
        }


@dataclass
class PostToolUseEvent:
    """工具執行後成功(回值忽略)。"""

    type: Literal["PostToolUse"] = "PostToolUse"
    tool: Tool[Any] | None = None
    tool_input: dict[str, Any] | None = None
    result_text: str = ""
    is_error: bool = False
    ctx: AgentContext | None = None

    session_id: str | None = None
    user_id: str | None = None
    tool_name: str | None = None
    tool_use_id: str | None = None

    def to_serializable(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "tool_name": self.tool_name or (self.tool.name if self.tool else None),
            "tool_use_id": self.tool_use_id,
            "tool_input": self.tool_input,
            "result_text": self.result_text,
            "is_error": self.is_error,
        }


# ─── events ─────────────────────────────────────────────────────────


@dataclass
class PostToolUseFailureEvent:
    """工具拋例外 / 失敗(獨立於 PostToolUse)。"""

    type: Literal["PostToolUseFailure"] = "PostToolUseFailure"
    tool: Tool[Any] | None = None
    tool_input: dict[str, Any] | None = None
    error_message: str = ""
    ctx: AgentContext | None = None

    session_id: str | None = None
    user_id: str | None = None
    tool_name: str | None = None
    tool_use_id: str | None = None

    def to_serializable(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "tool_name": self.tool_name or (self.tool.name if self.tool else None),
            "tool_use_id": self.tool_use_id,
            "tool_input": self.tool_input,
            "error_message": self.error_message,
        }


@dataclass
class UserPromptSubmitEvent:
    """使用者送入新 prompt(Conversation.send 入口)。

    Hook 可:
    - 回 UserPromptSubmitResult(abort=True)→ 拒絕該 prompt
    - 回 UserPromptSubmitResult(additional_context=...)→ 注入 system prompt
    """

    type: Literal["UserPromptSubmit"] = "UserPromptSubmit"
    prompt: str = ""
    ctx: AgentContext | None = None
    session_id: str | None = None
    user_id: str | None = None

    def to_serializable(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "prompt": self.prompt,
        }


@dataclass
class SessionStartEvent:
    """Conversation 物件建立或 resume。"""

    type: Literal["SessionStart"] = "SessionStart"
    cwd: str = ""
    resumed: bool = False
    ctx: AgentContext | None = None
    session_id: str | None = None
    user_id: str | None = None

    def to_serializable(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "cwd": self.cwd,
            "resumed": self.resumed,
        }


@dataclass
class SetupEvent:
    """應用程式啟動(FastAPI lifespan / CLI 第一次跑)。"""

    type: Literal["Setup"] = "Setup"
    ctx: AgentContext | None = None
    session_id: str | None = None
    user_id: str | None = None

    def to_serializable(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "session_id": self.session_id,
            "user_id": self.user_id,
        }


@dataclass
class SubagentStartEvent:
    """AgentTool 開子 agent。"""

    type: Literal["SubagentStart"] = "SubagentStart"
    parent_session_id: str = ""
    subagent_type: str = ""
    prompt: str = ""
    ctx: AgentContext | None = None
    session_id: str | None = None
    user_id: str | None = None

    def to_serializable(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "parent_session_id": self.parent_session_id,
            "subagent_type": self.subagent_type,
            "prompt": self.prompt,
        }


@dataclass
class FileChangedEvent:
    """FileWriteTool / FileEditTool 成功改檔。"""

    type: Literal["FileChanged"] = "FileChanged"
    file_path: str = ""
    change_type: Literal["created", "modified", "deleted"] = "modified"
    ctx: AgentContext | None = None
    session_id: str | None = None
    user_id: str | None = None

    def to_serializable(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "file_path": self.file_path,
            "change_type": self.change_type,
        }


HookEvent = (
    PreToolUseEvent
    | PostToolUseEvent
    | PostToolUseFailureEvent
    | UserPromptSubmitEvent
    | SessionStartEvent
    | SetupEvent
    | SubagentStartEvent
    | FileChangedEvent
)


HookEventName = Literal[
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "UserPromptSubmit",
    "SessionStart",
    "Setup",
    "SubagentStart",
    "FileChanged",
]


HOOK_EVENT_NAMES: tuple[str, ...] = (
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "UserPromptSubmit",
    "SessionStart",
    "Setup",
    "SubagentStart",
    "FileChanged",
)


# ─── Result 型別(部份 hook 可回值改變主流程)──────────────────────────────


@dataclass
class PreToolUseResult:
    """PreToolUse hook 回值。

    - abort=True → 阻擋工具(同 回 False)
    - modified_input=... → 改 tool input(覆蓋 caller 給的)
    """

    abort: bool = False
    abort_reason: str | None = None
    modified_input: dict[str, Any] | None = None
    additional_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class UserPromptSubmitResult:
    """UserPromptSubmit hook 回值。

    - abort=True → 拒絕 prompt(Conversation.send 不送出)
    - additional_context → 注入 system prompt(append)
    """

    abort: bool = False
    abort_reason: str | None = None
    additional_context: str | None = None


def _str_uuid(u: UUID | str | None) -> str | None:
    """工具:UUID → str(便利 to_serializable 用)。"""
    if u is None:
        return None
    return str(u)
