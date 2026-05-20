"""/preferences。

REST endpoints 管理 per-user / per-conversation custom instructions。

- GET /me/custom-instructions → 取 user-level
- PUT /me/custom-instructions → 設 user-level(空字串 / null = 清除)
- GET /sessions/{sid}/custom-instructions → 取 conversation-level
- PUT /sessions/{sid}/custom-instructions → 設 conversation-level

對應 ChatGPT 的「About me」/「Custom Instructions for this chat」。
所有 endpoint JWT-protected。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from orion_chat_api.deps import current_user
from orion_sdk.prompt.instructions import (
    CONVERSATION_INSTRUCTION_LIMIT_CHARS,
    USER_INSTRUCTION_LIMIT_CHARS,
    get_custom_instructions,
    upsert_conversation_instructions,
    upsert_user_instructions,
)
from orion_sdk.storage.db.engine import db_session

router = APIRouter()


class CustomInstructionsBody(BaseModel):
    instructions: str | None = None
    """要設定的內容。None / 空字串 → 清除。"""


class CustomInstructionsResponse(BaseModel):
    user_level: str | None
    conversation_level: str | None


async def _require_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """從 app.state.db_engine 取 session;沒設 ORION_DB_URL 就 503。"""
    engine = getattr(request.app.state, "db_engine", None)
    if engine is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Custom instructions require ORION_DB_URL to be set.",
        )
    async with db_session(engine) as session:
        yield session


@router.get("/me/custom-instructions", response_model=CustomInstructionsResponse)
async def get_user_instructions(
    user_id: Annotated[str, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(_require_db)],
) -> CustomInstructionsResponse:
    inst = await get_custom_instructions(
        user_id=user_id, session_id=None, db=db,
    )
    return CustomInstructionsResponse(
        user_level=inst.user_level,
        conversation_level=None,
    )


@router.put("/me/custom-instructions", response_model=CustomInstructionsResponse)
async def put_user_instructions(
    body: CustomInstructionsBody,
    user_id: Annotated[str, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(_require_db)],
) -> CustomInstructionsResponse:
    if body.instructions and len(body.instructions) > USER_INSTRUCTION_LIMIT_CHARS * 2:
        # 守門:超過 2x limit 直接拒(server 側 truncate 沒意義 — UI 應自己擋)
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"instructions too long (max {USER_INSTRUCTION_LIMIT_CHARS * 2} chars).",
        )
    await upsert_user_instructions(
        user_id=user_id, instructions=body.instructions, db=db,
    )
    inst = await get_custom_instructions(
        user_id=user_id, session_id=None, db=db,
    )
    return CustomInstructionsResponse(
        user_level=inst.user_level,
        conversation_level=None,
    )


@router.get(
    "/sessions/{sid}/custom-instructions", response_model=CustomInstructionsResponse,
)
async def get_session_instructions(
    sid: UUID,
    user_id: Annotated[str, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(_require_db)],
) -> CustomInstructionsResponse:
    inst = await get_custom_instructions(
        user_id=user_id, session_id=str(sid), db=db,
    )
    return CustomInstructionsResponse(
        user_level=inst.user_level,
        conversation_level=inst.conversation_level,
    )


@router.put(
    "/sessions/{sid}/custom-instructions", response_model=CustomInstructionsResponse,
)
async def put_session_instructions(
    sid: UUID,
    body: CustomInstructionsBody,
    user_id: Annotated[str, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(_require_db)],
) -> CustomInstructionsResponse:
    if (
        body.instructions
        and len(body.instructions) > CONVERSATION_INSTRUCTION_LIMIT_CHARS * 2
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"instructions too long (max {CONVERSATION_INSTRUCTION_LIMIT_CHARS * 2} chars).",
        )
    await upsert_conversation_instructions(
        session_id=str(sid), instructions=body.instructions, db=db,
    )
    inst = await get_custom_instructions(
        user_id=user_id, session_id=str(sid), db=db,
    )
    return CustomInstructionsResponse(
        user_level=inst.user_level,
        conversation_level=inst.conversation_level,
    )
