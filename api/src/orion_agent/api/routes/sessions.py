"""/sessions — REST CRUD + /models — 可選 model 清單。

- POST /sessions → 建新 conversation,可選帶 provider/model;回 session_id + provider/model
- GET /sessions → 列出 user 所有 session 摘要(含 provider/model)
- GET /sessions/{sid} → 單 session 摘要
- DELETE /sessions/{sid} → 刪 session
- GET /models → catalog + 各 provider 的 API key 是否設好(client 用來灰掉沒 key 的選項)
"""

from __future__ import annotations

import os
from typing import Annotated, Literal
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
from orion_agent.llm.catalog import list_catalog, validate
from orion_agent.llm.provider import LLMProvider, get_provider
from orion_agent.telemetry.cost_tracker import get_session_summary

router = APIRouter()


_PROVIDER_KEY_ENV: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


class CreateSessionRequest(BaseModel):
    """建 session 可選指定 (provider, model)。一者帶就兩者都得帶。"""

    provider: Literal["anthropic", "openai"] | None = None
    model: str | None = None


class SessionSummary(BaseModel):
    session_id: UUID
    user_id: str
    n_messages: int
    n_turns: int
    provider: str
    model: str


@router.post("/sessions", response_model=SessionSummary, status_code=status.HTTP_201_CREATED)
async def create_session(
    user_id: Annotated[str, Depends(current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
    default_provider: Annotated[LLMProvider, Depends(get_llm_provider)],
    body: CreateSessionRequest | None = None,
) -> SessionSummary:
    provider_for_session: LLMProvider
    if body is None or (body.provider is None and body.model is None):
        provider_for_session = default_provider
    elif body.provider is None or body.model is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "must specify both 'provider' and 'model' (or neither for server default)",
        )
    else:
        if not validate(body.provider, body.model):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"invalid (provider, model): ({body.provider!r}, {body.model!r})",
            )
        env_key = _PROVIDER_KEY_ENV[body.provider]
        if not os.environ.get(env_key):
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                f"{body.provider} key not configured (set {env_key})",
            )
        provider_for_session = get_provider(body.provider, body.model)

    conv = Conversation(provider=provider_for_session, user_id=user_id)
    sid = await sm.create(
        user_id=user_id, session_id=conv.session_id, conversation=conv,
    )
    return SessionSummary(
        session_id=sid,
        user_id=user_id,
        n_messages=0,
        n_turns=0,
        provider=provider_for_session.name,
        model=provider_for_session.model,
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
            provider=i.provider,
            model=i.model,
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
        provider=conv.provider.name,
        model=conv.provider.model,
    )


@router.get("/sessions/{session_id}/cost")
async def session_cost(
    session_id: UUID,
    user_id: Annotated[str, Depends(current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> dict[str, object]:
    """Phase 9:回該 session 的 token / cost 摘要。"""
    conv = await sm.get(user_id, session_id)
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    summary = get_session_summary(str(session_id))
    if summary is None:
        return {
            "session_id": str(session_id),
            "user_id": user_id,
            "total_cost_usd": 0.0,
            "cache_hit_ratio": 0.0,
            "total_api_duration_ms": 0.0,
            "by_model": {},
        }
    return summary


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: UUID,
    user_id: Annotated[str, Depends(current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> None:
    deleted = await sm.delete(user_id, session_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")


@router.get("/models")
async def list_models(
    default_provider: Annotated[LLMProvider, Depends(get_llm_provider)],
    _user_id: Annotated[str, Depends(current_user)],
) -> dict[str, object]:
    """回 catalog + 哪個 provider 的 API key 設好了(UI 用來灰掉沒 key 的選項)。"""
    catalog = list_catalog()
    providers_raw = catalog["providers"]
    assert isinstance(providers_raw, list)
    providers = [
        {
            **p,
            "available": bool(os.environ.get(_PROVIDER_KEY_ENV[p["id"]])),
        }
        for p in providers_raw
    ]
    return {
        "providers": providers,
        "default": {
            "provider": default_provider.name,
            "model": default_provider.model,
        },
    }
