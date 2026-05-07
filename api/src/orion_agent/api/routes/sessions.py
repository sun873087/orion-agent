"""/sessions — REST CRUD。

- POST /sessions → 建新 conversation,回 session_id
- GET /sessions → 列出 user 所有 session 摘要
- GET /sessions/{sid} → 單 session 摘要
- DELETE /sessions/{sid} → 刪 session
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from orion_agent.api.deps import (
    current_user,
    get_llm_provider,
    get_session_manager,
)
from orion_agent.api.session_manager import SessionManager
from orion_agent.core.conversation import Conversation
from orion_agent.llm.provider import LLMProvider

router = APIRouter()


class CreateSessionRequest(BaseModel):
    """可選帶 provider / model / session 設定 override。Phase 7 加更多。"""

    pass


class SessionSummary(BaseModel):
    session_id: UUID
    user_id: str
    n_messages: int
    n_turns: int


@router.post("/sessions", response_model=SessionSummary, status_code=status.HTTP_201_CREATED)
async def create_session(
    user_id: Annotated[str, Depends(current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
    provider: Annotated[LLMProvider, Depends(get_llm_provider)],
    body: CreateSessionRequest | None = None,  # noqa: ARG001 — Phase 7 用
) -> SessionSummary:
    conv = Conversation(
        provider=provider,
        user_id=user_id,
        # 其他欄位走預設(memory_enabled=True / persistence_enabled=True)
    )
    sid = await sm.create(user_id=user_id, session_id=conv.session_id, conversation=conv)
    return SessionSummary(
        session_id=sid, user_id=user_id, n_messages=0, n_turns=0,
    )


@router.get("/sessions", response_model=list[SessionSummary])
async def list_sessions(
    user_id: Annotated[str, Depends(current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> list[SessionSummary]:
    items = await sm.list_for_user(user_id)
    return [
        SessionSummary(
            session_id=i.session_id,
            user_id=i.user_id,
            n_messages=i.n_messages,
            n_turns=i.n_turns,
        )
        for i in items
    ]


@router.get("/sessions/{session_id}", response_model=SessionSummary)
async def get_session(
    session_id: UUID,
    user_id: Annotated[str, Depends(current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> SessionSummary:
    conv = await sm.get(user_id, session_id)
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    return SessionSummary(
        session_id=session_id,
        user_id=user_id,
        n_messages=len(conv.state_messages),
        n_turns=conv.stats.turns,
    )


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: UUID,
    user_id: Annotated[str, Depends(current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> None:
    deleted = await sm.delete(user_id, session_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
