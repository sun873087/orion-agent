"""/auth/login — JWT(dev mode 任意 username 通過)。"""

from __future__ import annotations

from fastapi import APIRouter

from orion_agent.api.auth import LoginRequest, LoginResponse, issue_token

router = APIRouter()


@router.post("/auth/login", response_model=LoginResponse)
async def login(body: LoginRequest) -> LoginResponse:
    """Dev 模式登入。Phase 7 換真 user DB / OAuth。"""
    return issue_token(body.username)
