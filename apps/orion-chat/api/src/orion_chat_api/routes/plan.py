"""/sessions/{sid}/plan/* — plan mode 狀態機(per-session)。

inactive → enter → active → submit → awaiting_approval → approve → inactive
                                                        → reject  → active

enforcement(active=唯讀白名單、awaiting=全 deny)由 chat.py 在每個 turn 用 SDK
plan_mode_aware + ctx.plan_mode_state 套上。模型自動 call EnterPlanMode/ExitPlanMode
的整合留待後續(目前 enter/submit 由 UI / host 驅動)。
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from starlette.requests import Request

from orion_chat_api.conversation_meta import (
    fetch_plan,
    session_belongs_to,
    upsert_meta,
)
from orion_chat_api.deps import current_user

router = APIRouter()


class PlanStatusResponse(BaseModel):
    status: str
    content: str = ""


class SubmitPlanBody(BaseModel):
    content: str = ""


async def _engine_and_owned(request: Request, session_id: UUID, user_id: str):  # type: ignore[no-untyped-def]
    engine = getattr(request.app.state, "db_engine", None)
    if engine is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "plan mode requires ORION_DB_URL",
        )
    if not await session_belongs_to(engine, str(session_id), user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    return engine


@router.get("/sessions/{session_id}/plan/status", response_model=PlanStatusResponse)
async def plan_status(
    session_id: UUID,
    request: Request,
    user_id: Annotated[str, Depends(current_user)],
) -> PlanStatusResponse:
    engine = await _engine_and_owned(request, session_id, user_id)
    st, content = await fetch_plan(engine, str(session_id))
    return PlanStatusResponse(status=st, content=content)


@router.post("/sessions/{session_id}/plan/enter", response_model=PlanStatusResponse)
async def plan_enter(
    session_id: UUID,
    request: Request,
    user_id: Annotated[str, Depends(current_user)],
) -> PlanStatusResponse:
    engine = await _engine_and_owned(request, session_id, user_id)
    await upsert_meta(
        engine, str(session_id), plan_mode_status="active", plan_content="",
    )
    return PlanStatusResponse(status="active")


@router.post("/sessions/{session_id}/plan/submit", response_model=PlanStatusResponse)
async def plan_submit(
    session_id: UUID,
    body: SubmitPlanBody,
    request: Request,
    user_id: Annotated[str, Depends(current_user)],
) -> PlanStatusResponse:
    engine = await _engine_and_owned(request, session_id, user_id)
    await upsert_meta(
        engine,
        str(session_id),
        plan_mode_status="awaiting_approval",
        plan_content=body.content,
    )
    return PlanStatusResponse(status="awaiting_approval", content=body.content)


@router.post("/sessions/{session_id}/plan/approve", response_model=PlanStatusResponse)
async def plan_approve(
    session_id: UUID,
    request: Request,
    user_id: Annotated[str, Depends(current_user)],
) -> PlanStatusResponse:
    engine = await _engine_and_owned(request, session_id, user_id)
    await upsert_meta(engine, str(session_id), plan_mode_status="inactive")
    return PlanStatusResponse(status="inactive")


@router.post("/sessions/{session_id}/plan/reject", response_model=PlanStatusResponse)
async def plan_reject(
    session_id: UUID,
    request: Request,
    user_id: Annotated[str, Depends(current_user)],
) -> PlanStatusResponse:
    """退回 planning(回 active),清掉草稿 plan。"""
    engine = await _engine_and_owned(request, session_id, user_id)
    await upsert_meta(
        engine, str(session_id), plan_mode_status="active", plan_content="",
    )
    return PlanStatusResponse(status="active")


@router.post("/sessions/{session_id}/plan/exit", response_model=PlanStatusResponse)
async def plan_exit(
    session_id: UUID,
    request: Request,
    user_id: Annotated[str, Depends(current_user)],
) -> PlanStatusResponse:
    engine = await _engine_and_owned(request, session_id, user_id)
    await upsert_meta(
        engine, str(session_id), plan_mode_status="inactive", plan_content="",
    )
    return PlanStatusResponse(status="inactive")
