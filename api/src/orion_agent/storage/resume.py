"""Resume — 從 transcript JSONL 重建 conversation 狀態。

對應 TS Claude Code `src/commands/resume/resume.tsx` + `reconstructContentReplacementState`。

讀取 transcript,從 record 還原:
- system_prompt(從 session-meta record)
- messages(從 message records)
- ContentReplacementState(從 tool-result-replacement records + 已 seen 的 tool_use_id)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from orion_agent.llm.types import (
    ContentBlock,
    ImageBlock,
    NormalizedMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from orion_agent.storage.paths import session_paths
from orion_agent.storage.replacement_state import (
    ContentReplacementState,
    reconstruct_content_replacement_state,
)
from orion_agent.storage.session import iter_records_sync


@dataclass
class SessionSnapshot:
    """Resume 時用的整包快照。"""

    session_id: UUID
    system_prompt: str = ""
    provider: str = ""
    model: str = ""
    messages: list[NormalizedMessage] = field(default_factory=list)
    replacement_state: ContentReplacementState = field(default_factory=ContentReplacementState)
    transitions: list[dict[str, Any]] = field(default_factory=list)


def _block_from_dict(d: dict[str, Any]) -> ContentBlock | None:
    """單一 ContentBlock 反序列化。"""
    btype = d.get("type")
    if btype == "text":
        return TextBlock(text=d.get("text", ""))
    if btype == "tool_use":
        return ToolUseBlock(
            id=d.get("id", ""),
            name=d.get("name", ""),
            input=d.get("input", {}),
        )
    if btype == "tool_result":
        return ToolResultBlock(
            tool_use_id=d.get("tool_use_id", ""),
            content=d.get("content", ""),
            is_error=d.get("is_error", False),
        )
    if btype == "image":
        return ImageBlock(
            media_type=d.get("media_type", "image/png"),
            data=d.get("data", ""),
        )
    if btype == "thinking":
        return ThinkingBlock(text=d.get("text", ""))
    return None


def _message_from_dict(d: dict[str, Any]) -> NormalizedMessage | None:
    role = d.get("role")
    if role not in ("user", "assistant", "system"):
        return None
    raw_content = d.get("content", "")
    if isinstance(raw_content, str):
        return NormalizedMessage(role=role, content=raw_content)
    if isinstance(raw_content, list):
        blocks: list[ContentBlock] = []
        for item in raw_content:
            if isinstance(item, dict):
                b = _block_from_dict(item)
                if b is not None:
                    blocks.append(b)
        return NormalizedMessage(role=role, content=blocks)
    return None


def load_session(session_id: UUID) -> SessionSnapshot:
    """讀整個 transcript 重建 SessionSnapshot。"""
    sp = session_paths(session_id)
    records = iter_records_sync(sp.transcript)

    snapshot = SessionSnapshot(session_id=session_id)
    replacement_records: list[dict[str, Any]] = []

    for r in records:
        kind = r.get("kind")
        if kind == "session-meta":
            snapshot.provider = r.get("provider", "")
            snapshot.model = r.get("model", "")
            snapshot.system_prompt = r.get("system_prompt", "")
        elif kind == "message":
            msg_dict = r.get("message")
            if isinstance(msg_dict, dict):
                msg = _message_from_dict(msg_dict)
                if msg is not None:
                    snapshot.messages.append(msg)
        elif kind == "tool-result-replacement":
            replacement_records.append(r)
        elif kind == "transition":
            snapshot.transitions.append(r)

    snapshot.replacement_state = reconstruct_content_replacement_state(
        snapshot.messages,
        replacement_records,
    )
    return snapshot
