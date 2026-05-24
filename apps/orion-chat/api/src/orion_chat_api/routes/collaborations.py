"""/collaborations — 多 pane 協作容器(限同一 user 的多 session)。

create / list / delete + 把 session 加入(add pane)/ 移出。**跨 pane DispatchPane
執行**(pane A 觸發 pane B 的 turn)與 MultiPaneView 並排即時渲染是路線圖後續項目
(需背景 turn 注入,類似 scheduler daemon)。限同一 user — 不做跨 user team。
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.requests import Request

from orion_chat_api.conversation_meta import session_belongs_to, upsert_meta
from orion_chat_api.deps import current_user
from orion_sdk.storage.db.engine import db_session
from orion_sdk.storage.db.models import (
    Collaboration as CollaborationRow,
    ConversationMetadata,
)

router = APIRouter()


def _engine(request: Request) -> AsyncEngine:
    engine = getattr(request.app.state, "db_engine", None)
    if engine is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "collaborations require ORION_DB_URL",
        )
    return engine


class CollaborationBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class CollaborationSummary(BaseModel):
    id: str
    name: str
    pane_session_ids: list[str] = []


class AddPaneBody(BaseModel):
    session_id: str


async def _owned(engine: AsyncEngine, collab_id: str, user_id: str) -> CollaborationRow:
    async with db_session(engine) as db:
        row = (
            await db.execute(
                select(CollaborationRow).where(
                    CollaborationRow.id == collab_id,
                    CollaborationRow.user_id == user_id,
                ),
            )
        ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "collaboration not found")
    return row


async def _pane_ids(engine: AsyncEngine, collab_id: str) -> list[str]:
    async with db_session(engine) as db:
        rows = (
            await db.execute(
                select(ConversationMetadata.session_id).where(
                    ConversationMetadata.collaboration_id == collab_id,
                ),
            )
        ).all()
    return [r[0] for r in rows]


@router.get("/collaborations", response_model=list[CollaborationSummary])
async def list_collaborations(
    request: Request,
    user_id: Annotated[str, Depends(current_user)],
) -> list[CollaborationSummary]:
    engine = _engine(request)
    async with db_session(engine) as db:
        rows = (
            await db.execute(
                select(CollaborationRow)
                .where(CollaborationRow.user_id == user_id)
                .order_by(CollaborationRow.created_at.desc()),
            )
        ).scalars().all()
    out: list[CollaborationSummary] = []
    for r in rows:
        out.append(
            CollaborationSummary(
                id=r.id, name=r.name, pane_session_ids=await _pane_ids(engine, r.id),
            ),
        )
    return out


@router.post(
    "/collaborations",
    response_model=CollaborationSummary,
    status_code=status.HTTP_201_CREATED,
)
async def create_collaboration(
    body: CollaborationBody,
    request: Request,
    user_id: Annotated[str, Depends(current_user)],
) -> CollaborationSummary:
    engine = _engine(request)
    row = CollaborationRow(id=str(uuid4()), user_id=user_id, name=body.name)
    async with db_session(engine) as db:
        db.add(row)
        await db.commit()
    return CollaborationSummary(id=row.id, name=row.name)


@router.delete("/collaborations/{collab_id}")
async def delete_collaboration(
    collab_id: str,
    request: Request,
    user_id: Annotated[str, Depends(current_user)],
) -> dict[str, bool]:
    engine = _engine(request)
    await _owned(engine, collab_id, user_id)
    async with db_session(engine) as db:
        await db.execute(
            delete(CollaborationRow).where(CollaborationRow.id == collab_id),
        )
        await db.commit()
    return {"deleted": True}


@router.put("/collaborations/{collab_id}/panes", response_model=CollaborationSummary)
async def add_pane(
    collab_id: str,
    body: AddPaneBody,
    request: Request,
    user_id: Annotated[str, Depends(current_user)],
) -> CollaborationSummary:
    """把一個 session 加進協作當 pane(限自己的 session)。"""
    engine = _engine(request)
    collab = await _owned(engine, collab_id, user_id)
    if not await session_belongs_to(engine, body.session_id, user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    await upsert_meta(engine, body.session_id, collaboration_id=collab_id)
    return CollaborationSummary(
        id=collab.id, name=collab.name, pane_session_ids=await _pane_ids(engine, collab_id),
    )
