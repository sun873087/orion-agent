"""Resume — 從 transcript JSONL 重建 conversation 狀態。

對應 TS Claude Code `src/commands/resume/resume.tsx` + `reconstructContentReplacementState`。

讀取 transcript,從 record 還原:
- system_prompt(從 session-meta record)
- messages(從 message records)
- ContentReplacementState(從 tool-result-replacement records + 已 seen 的 tool_use_id)

Phase 27:`load_session(sid, engine=...)` 時優先讀 DB messages 表;
DB 無資料(舊 session / DB engine = None)走 JSONL fallback。
transitions / replacements 永遠走 JSONL(沒對應 DB 表)。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine

from orion_model.types import (
    ContentBlock,
    ImageBlock,
    NormalizedMessage,
    TextBlock,
    ThinkingBlock,
    TombstoneBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from orion_sdk.storage.paths import session_paths
from orion_sdk.storage.replacement_state import (
    ContentReplacementState,
    reconstruct_content_replacement_state,
)
from orion_sdk.storage.session import iter_records_sync


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
    warnings: list[str] = field(default_factory=list)
    """resume 時偵測到的問題(dangling tool_use auto-repair 等)。"""


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
    if btype == "tombstone":
        return TombstoneBlock(
            summary=d.get("summary", ""),
            range_start_msg_index=d.get("range_start_msg_index", 0),
            range_end_msg_index=d.get("range_end_msg_index", 0),
            original_token_count=d.get("original_token_count", 0),
            captured_at=d.get("captured_at", ""),
        )
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


def validate_and_repair_messages(
    messages: list[NormalizedMessage],
) -> tuple[list[NormalizedMessage], list[str]]:
    """檢查每個 ToolUseBlock 都有對應 ToolResultBlock。

    Dangling tool_use(無對應 result)= session 被中途 kill 在 tool 執行中。
    Auto-repair:在那則 assistant message 後插一則 synthetic user message,
    內含 ToolResultBlock(is_error=True),讓 resume 後的 conversation 對齊
    Anthropic / OpenAI 的「tool_use 必有 tool_result 後接」契約。

    Returns:
        (repaired_messages, warnings)— 沒有 dangling 時 messages 原樣回。
    """
    warnings: list[str] = []

    # 蒐集所有 tool_use 與 tool_result IDs
    tool_use_info: list[tuple[int, str, str]] = []  # (msg_idx, id, name)
    tool_result_ids: set[str] = set()

    for i, m in enumerate(messages):
        if not isinstance(m.content, list):
            continue
        for block in m.content:
            if isinstance(block, ToolUseBlock):
                tool_use_info.append((i, block.id, block.name))
            elif isinstance(block, ToolResultBlock):
                tool_result_ids.add(block.tool_use_id)

    by_msg_idx: dict[int, list[tuple[str, str]]] = defaultdict(list)
    for msg_idx, tu_id, tu_name in tool_use_info:
        if tu_id not in tool_result_ids:
            by_msg_idx[msg_idx].append((tu_id, tu_name))
            warnings.append(
                f"dangling tool_use id={tu_id!r} ({tu_name!r}) in message[{msg_idx}] "
                "— appending synthetic error result for resume safety"
            )

    if not by_msg_idx:
        return list(messages), warnings

    repaired: list[NormalizedMessage] = []
    for i, m in enumerate(messages):
        repaired.append(m)
        if i in by_msg_idx:
            synthetic_blocks: list[ContentBlock] = [
                ToolResultBlock(
                    tool_use_id=tu_id,
                    content=(
                        f"(tool {tu_name!r} did not complete — session was "
                        "interrupted before the result was recorded; treating as error)"
                    ),
                    is_error=True,
                )
                for tu_id, tu_name in by_msg_idx[i]
            ]
            repaired.append(
                NormalizedMessage(role="user", content=synthetic_blocks)
            )

    return repaired, warnings


async def fetch_db_messages(
    session_id: UUID,
    engine: AsyncEngine,
) -> list[NormalizedMessage] | None:
    """Phase 27:async 讀 DB messages 表。

    給 caller(DbSessionManager)在 async context 預先 await 拿到 messages,再把結果
    透過 `prebaked_messages` 傳進 sync load_session。這樣避免 sync 路徑跑 sync engine
    對 `:memory:` SQLite 看不到 async engine 寫入的問題。

    DB 無 row → 回 None。
    """
    from sqlalchemy import select

    from orion_sdk.storage.db.engine import db_session
    from orion_sdk.storage.db.models import Message as MessageRow

    async with db_session(engine) as db:
        stmt = (
            select(MessageRow.role, MessageRow.content_json)
            .where(MessageRow.session_id == str(session_id))
            .order_by(MessageRow.created_at, MessageRow.id)
        )
        rows = list(await db.execute(stmt))

    if not rows:
        return None
    messages: list[NormalizedMessage] = []
    for role, content_json in rows:
        msg_dict = {"role": role, "content": content_json}
        msg = _message_from_dict(msg_dict)
        if msg is not None:
            messages.append(msg)
    return messages


def load_session(
    session_id: UUID,
    engine: AsyncEngine | None = None,  # noqa: ARG001 — kept for back-compat; use prebaked_messages
    *,
    prebaked_messages: list[NormalizedMessage] | None = None,
) -> SessionSnapshot:
    """讀整個 transcript 重建 SessionSnapshot。

    Phase 27:若 `prebaked_messages` 提供(caller 已 async 從 DB 撈出),用該 list 作
    canonical messages;否則 messages 走 JSONL(legacy / CLI no-DB)。transitions /
    replacements 永遠 JSONL。`engine` 參數保留為 backwards-compat 標記,實際不使用 —
    讓 DbSessionManager 等 caller 提前 `await fetch_db_messages(...)` 再傳進來。
    """
    sp = session_paths(session_id)
    records = iter_records_sync(sp.transcript)

    snapshot = SessionSnapshot(session_id=session_id)
    replacement_records: list[dict[str, Any]] = []
    jsonl_messages: list[NormalizedMessage] = []

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
                    jsonl_messages.append(msg)
        elif kind == "tool-result-replacement":
            replacement_records.append(r)
        elif kind == "transition":
            snapshot.transitions.append(r)

    # Phase 27:prebaked_messages(DB)優先;否則 JSONL
    snapshot.messages = (
        prebaked_messages if prebaked_messages is not None else jsonl_messages
    )

    # Auto-repair dangling tool_use(中途 kill 的 transcript)
    snapshot.messages, validation_warnings = validate_and_repair_messages(
        snapshot.messages,
    )
    snapshot.warnings.extend(validation_warnings)

    snapshot.replacement_state = reconstruct_content_replacement_state(
        snapshot.messages,
        replacement_records,
    )
    return snapshot
