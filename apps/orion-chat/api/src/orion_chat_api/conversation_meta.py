"""ConversationMetadata 的 title / starred 讀寫(chat-api 專屬,DB-backed)。

custom_instructions 已由 orion_sdk.prompt.instructions 處理;title / starred 是
chat-api UI 層概念(sidebar 顯示 + 置頂),放這層而非 SDK。

title 由首輪後的 side-query 自動生成(chat.py),也可由 PATCH /sessions/{sid}
手動改;starred 由 PATCH 切換。所有寫入 idempotent upsert。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from orion_sdk.storage.db.engine import db_session
from orion_sdk.storage.db.models import (
    ConversationMetadata,
    Session as SessionRow,
)

_UNSET: Any = object()


async def fetch_meta_map(
    engine: AsyncEngine, session_ids: list[str],
) -> dict[str, tuple[str | None, bool]]:
    """批次取 {session_id: (title, starred)}。沒 metadata row 的不在 map 裡。"""
    if not session_ids:
        return {}
    async with db_session(engine) as db:
        rows = (
            await db.execute(
                select(ConversationMetadata).where(
                    ConversationMetadata.session_id.in_(session_ids),
                ),
            )
        ).scalars().all()
    return {r.session_id: (r.title, bool(r.starred)) for r in rows}


async def session_belongs_to(
    engine: AsyncEngine, session_id: str, user_id: str,
) -> bool:
    """驗 session 屬於該 user(PATCH 前的 ownership check)。"""
    async with db_session(engine) as db:
        row = (
            await db.execute(
                select(SessionRow.id).where(
                    SessionRow.id == session_id,
                    SessionRow.user_id == user_id,
                ),
            )
        ).first()
    return row is not None


def budget_is_exceeded(total_cost_usd: float, cap: float | None) -> bool:
    """純函式 — 是否已達/超過上限。cap=None → 永不超過。"""
    return cap is not None and total_cost_usd >= cap


async def fetch_plan(engine: AsyncEngine, session_id: str) -> tuple[str, str]:
    """回 (plan_mode_status, plan_content)。預設 ('inactive', '')。"""
    async with db_session(engine) as db:
        row = (
            await db.execute(
                select(
                    ConversationMetadata.plan_mode_status,
                    ConversationMetadata.plan_content,
                ).where(ConversationMetadata.session_id == session_id),
            )
        ).first()
    if row is None:
        return ("inactive", "")
    status, content = row
    return (status or "inactive", content or "")


async def fetch_session_context(
    engine: AsyncEngine, session_id: str,
) -> tuple[str | None, str | None]:
    """回 (project_id, active_role)。沒 metadata 都是 None。"""
    async with db_session(engine) as db:
        row = (
            await db.execute(
                select(
                    ConversationMetadata.project_id,
                    ConversationMetadata.active_role,
                ).where(ConversationMetadata.session_id == session_id),
            )
        ).first()
    if row is None:
        return (None, None)
    return (row[0], row[1])


async def fetch_permission_mode(engine: AsyncEngine, session_id: str) -> str:
    """回 'ask' / 'act'(預設 'ask')。"""
    async with db_session(engine) as db:
        row = (
            await db.execute(
                select(ConversationMetadata.permission_mode).where(
                    ConversationMetadata.session_id == session_id,
                ),
            )
        ).scalar_one_or_none()
    return row if row in ("ask", "act") else "ask"


async def fetch_budget(
    engine: AsyncEngine, session_id: str,
) -> tuple[float | None, bool]:
    """回 (budget_usd_cap, budget_exceeded)。"""
    async with db_session(engine) as db:
        row = (
            await db.execute(
                select(ConversationMetadata).where(
                    ConversationMetadata.session_id == session_id,
                ),
            )
        ).scalar_one_or_none()
    if row is None:
        return (None, False)
    return (row.budget_usd_cap, bool(row.budget_exceeded))


async def upsert_meta(
    engine: AsyncEngine,
    session_id: str,
    *,
    title: str | None = _UNSET,
    starred: bool = _UNSET,
    parent_session_id: str | None = _UNSET,
    forked_from_message_index: int | None = _UNSET,
    budget_usd_cap: float | None = _UNSET,
    budget_exceeded: bool = _UNSET,
    permission_mode: str = _UNSET,
    plan_mode_status: str = _UNSET,
    plan_content: str = _UNSET,
    project_id: str | None = _UNSET,
    active_role: str | None = _UNSET,
    collaboration_id: str | None = _UNSET,
) -> tuple[str | None, bool]:
    """upsert metadata(只更新有傳的欄位)。回 (title, starred)。"""
    async with db_session(engine) as db:
        row = (
            await db.execute(
                select(ConversationMetadata).where(
                    ConversationMetadata.session_id == session_id,
                ),
            )
        ).scalar_one_or_none()
        if row is None:
            row = ConversationMetadata(session_id=session_id)
            db.add(row)
        if title is not _UNSET:
            row.title = title
        if starred is not _UNSET:
            row.starred = starred
        if parent_session_id is not _UNSET:
            row.parent_session_id = parent_session_id
        if forked_from_message_index is not _UNSET:
            row.forked_from_message_index = forked_from_message_index
        if budget_usd_cap is not _UNSET:
            row.budget_usd_cap = budget_usd_cap
        if budget_exceeded is not _UNSET:
            row.budget_exceeded = budget_exceeded
        if permission_mode is not _UNSET:
            row.permission_mode = permission_mode
        if plan_mode_status is not _UNSET:
            row.plan_mode_status = plan_mode_status
        if plan_content is not _UNSET:
            row.plan_content = plan_content
        if project_id is not _UNSET:
            row.project_id = project_id
        if active_role is not _UNSET:
            row.active_role = active_role
        if collaboration_id is not _UNSET:
            row.collaboration_id = collaboration_id
        await db.commit()
        return (row.title, bool(row.starred))
