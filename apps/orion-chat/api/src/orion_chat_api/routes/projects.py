"""/projects — per-user project CRUD + session 關聯。

project 掛 per-project 自訂指令 / workspace,組織多個 session。每個 query WHERE
user_id 隔離。custom_instructions 在每輪由 user_context.build_session_system_prefix
注入 system prompt;workspace 走 project_workspace_dir() 的 sandbox(見 chat.py runner)。
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.requests import Request

from orion_chat_api.conversation_meta import (
    fetch_session_context,
    session_belongs_to,
    upsert_meta,
)
from orion_chat_api.deps import current_user
from orion_sdk.storage.db.engine import db_session
from orion_sdk.storage.db.models import Project as ProjectRow

router = APIRouter()


def _engine(request: Request) -> AsyncEngine:
    engine = getattr(request.app.state, "db_engine", None)
    if engine is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "projects require ORION_DB_URL",
        )
    return engine


class ProjectBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    custom_instructions: str | None = None


class ProjectSummary(BaseModel):
    id: str
    name: str
    description: str | None = None
    custom_instructions: str | None = None


class SetProjectBody(BaseModel):
    project_id: str | None = None


def _to_summary(row: ProjectRow) -> ProjectSummary:
    return ProjectSummary(
        id=row.id,
        name=row.name,
        description=row.description,
        custom_instructions=row.custom_instructions,
    )


async def _owned_project(
    engine: AsyncEngine, project_id: str, user_id: str,
) -> ProjectRow:
    async with db_session(engine) as db:
        row = (
            await db.execute(
                select(ProjectRow).where(
                    ProjectRow.id == project_id, ProjectRow.user_id == user_id,
                ),
            )
        ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    return row


@router.get("/projects", response_model=list[ProjectSummary])
async def list_projects(
    request: Request,
    user_id: Annotated[str, Depends(current_user)],
) -> list[ProjectSummary]:
    engine = _engine(request)
    async with db_session(engine) as db:
        rows = (
            await db.execute(
                select(ProjectRow)
                .where(ProjectRow.user_id == user_id)
                .order_by(ProjectRow.created_at.desc()),
            )
        ).scalars().all()
    return [_to_summary(r) for r in rows]


@router.post(
    "/projects", response_model=ProjectSummary, status_code=status.HTTP_201_CREATED,
)
async def create_project(
    body: ProjectBody,
    request: Request,
    user_id: Annotated[str, Depends(current_user)],
) -> ProjectSummary:
    engine = _engine(request)
    row = ProjectRow(
        id=str(uuid4()),
        user_id=user_id,
        name=body.name,
        description=body.description,
        custom_instructions=body.custom_instructions,
    )
    async with db_session(engine) as db:
        db.add(row)
        await db.commit()
    return _to_summary(row)


@router.put("/projects/{project_id}", response_model=ProjectSummary)
async def update_project(
    project_id: str,
    body: ProjectBody,
    request: Request,
    user_id: Annotated[str, Depends(current_user)],
) -> ProjectSummary:
    engine = _engine(request)
    await _owned_project(engine, project_id, user_id)
    async with db_session(engine) as db:
        row = (
            await db.execute(
                select(ProjectRow).where(ProjectRow.id == project_id),
            )
        ).scalar_one()
        row.name = body.name
        row.description = body.description
        row.custom_instructions = body.custom_instructions
        await db.commit()
        return _to_summary(row)


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: str,
    request: Request,
    user_id: Annotated[str, Depends(current_user)],
) -> dict[str, bool]:
    engine = _engine(request)
    await _owned_project(engine, project_id, user_id)
    async with db_session(engine) as db:
        await db.execute(delete(ProjectRow).where(ProjectRow.id == project_id))
        await db.commit()
    return {"deleted": True}


@router.get("/sessions/{session_id}/project", response_model=dict)
async def get_session_project(
    session_id: UUID,
    request: Request,
    user_id: Annotated[str, Depends(current_user)],
) -> dict[str, str | None]:
    engine = _engine(request)
    if not await session_belongs_to(engine, str(session_id), user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    project_id, _role = await fetch_session_context(engine, str(session_id))
    return {"project_id": project_id}


@router.put("/sessions/{session_id}/project", response_model=dict)
async def set_session_project(
    session_id: UUID,
    body: SetProjectBody,
    request: Request,
    user_id: Annotated[str, Depends(current_user)],
) -> dict[str, str | None]:
    engine = _engine(request)
    if not await session_belongs_to(engine, str(session_id), user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    if body.project_id is not None:
        await _owned_project(engine, body.project_id, user_id)  # 驗 project 也是自己的
    await upsert_meta(engine, str(session_id), project_id=body.project_id)
    return {"project_id": body.project_id}
