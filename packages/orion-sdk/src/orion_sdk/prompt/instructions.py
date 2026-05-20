"""Custom instructions(Web chat 模式)。

對應 spec § 5.4(取代 TS `utils/claudemd.ts` 的 hierarchy)。Web chat 沒 cwd 概念,
改用兩層 instructions:

  - **User-level**:user 設一次,所有 conversation 共用(類 ChatGPT「About me」)
  - **Conversation-level**:單一 conversation 額外加(類 ChatGPT「Custom Instructions for this chat」)

兩層皆截斷至 5_000 chars(spec 預設;超過附 `...[truncated]`)。

CLI 模式(`prompt/context.py:find_instructions_files`)仍用 fs `instructions.md` —
本模組不取代,兩條路徑並存。caller 決定走哪條。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orion_sdk.storage.db.models import (
    ConversationMetadata,
    UserPreference,
)

USER_INSTRUCTION_LIMIT_CHARS = 5_000
CONVERSATION_INSTRUCTION_LIMIT_CHARS = 5_000

_TRUNCATED_SUFFIX = "\n\n...[truncated]"


@dataclass
class CustomInstructions:
    user_level: str | None = None
    conversation_level: str | None = None

    def is_empty(self) -> bool:
        return not (self.user_level or self.conversation_level)


def _truncate(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + _TRUNCATED_SUFFIX


async def get_custom_instructions(
    *,
    user_id: str,
    session_id: str | None,
    db: AsyncSession,
) -> CustomInstructions:
    """從 DB 讀兩層 instructions。

    Args:
        user_id: User.id(str)。
        session_id: Session.id(str)— None 表示沒指定 conversation,只讀 user-level。
        db: AsyncSession。

    Returns:
        CustomInstructions(空字串 / 不存在都回 None,caller 用 is_empty 判斷)。
    """
    pref = (
        await db.execute(
            select(UserPreference).where(UserPreference.user_id == user_id),
        )
    ).scalar_one_or_none()
    user_inst = (
        pref.custom_instructions if pref and pref.custom_instructions else None
    )

    conv_inst: str | None = None
    if session_id is not None:
        meta = (
            await db.execute(
                select(ConversationMetadata).where(
                    ConversationMetadata.session_id == session_id,
                ),
            )
        ).scalar_one_or_none()
        conv_inst = (
            meta.custom_instructions if meta and meta.custom_instructions else None
        )

    return CustomInstructions(
        user_level=_truncate(user_inst, USER_INSTRUCTION_LIMIT_CHARS),
        conversation_level=_truncate(
            conv_inst, CONVERSATION_INSTRUCTION_LIMIT_CHARS,
        ),
    )


def assemble_instructions_section(inst: CustomInstructions) -> str:
    """把 CustomInstructions 組成單一 markdown 字串(供加進 system prompt)。

    全空 → 回空字串。caller 應用 `if section: parts.append(section)` 模式。
    """
    if inst.is_empty():
        return ""
    parts: list[str] = []
    if inst.user_level:
        parts.append(f"## About this user\n\n{inst.user_level}")
    if inst.conversation_level:
        parts.append(
            f"## Context for this conversation\n\n{inst.conversation_level}"
        )
    return "\n\n".join(parts)


# ─── upsert helpers(REST endpoint 用)──────────────────────────────────────


async def upsert_user_instructions(
    *,
    user_id: str,
    instructions: str | None,
    db: AsyncSession,
) -> None:
    """寫(或清)user-level instructions。"""
    pref = (
        await db.execute(
            select(UserPreference).where(UserPreference.user_id == user_id),
        )
    ).scalar_one_or_none()

    cleaned: str | None = None
    if instructions and instructions.strip():
        cleaned = instructions.strip()

    if pref is None:
        pref = UserPreference(
            user_id=user_id,
            custom_instructions=cleaned,
        )
        db.add(pref)
    else:
        pref.custom_instructions = cleaned

    await db.commit()


async def upsert_conversation_instructions(
    *,
    session_id: str,
    instructions: str | None,
    db: AsyncSession,
) -> None:
    """寫(或清)conversation-level instructions。"""
    meta = (
        await db.execute(
            select(ConversationMetadata).where(
                ConversationMetadata.session_id == session_id,
            ),
        )
    ).scalar_one_or_none()

    cleaned: str | None = None
    if instructions and instructions.strip():
        cleaned = instructions.strip()

    if meta is None:
        meta = ConversationMetadata(
            session_id=session_id,
            custom_instructions=cleaned,
        )
        db.add(meta)
    else:
        meta.custom_instructions = cleaned

    await db.commit()


__all__ = [
    "CONVERSATION_INSTRUCTION_LIMIT_CHARS",
    "CustomInstructions",
    "USER_INSTRUCTION_LIMIT_CHARS",
    "assemble_instructions_section",
    "get_custom_instructions",
    "upsert_conversation_instructions",
    "upsert_user_instructions",
]
