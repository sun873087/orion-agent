"""/auth — login + register。

是 dev mode 任意 username 通過(/auth/login)。
加 /auth/register 與 DB-backed login。

行為:
- 若 app.state.db_engine 存在 → DB 模式(查 users 表)
- 否則 → dev fallback(任意 username 通過,**production 必設 ORION_DB_URL**)
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from orion_chat_api.auth import (
    Identity,
    LoginRequest,
    LoginResponse,
    dev_user_id,
    issue_token,
)
from orion_chat_api.auth_db import authenticate, create_user
from orion_chat_api.deps import current_identity
from orion_sdk.storage.db.engine import db_session

router = APIRouter()


class MeResponse(BaseModel):
    """`GET /me` 回應 — frontend 顯示 username / 區分 multi-account 用。"""

    user_id: str
    username: str


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=8, max_length=256)


class RegisterResponse(BaseModel):
    user_id: str
    username: str


class LoginWithPasswordRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(default="", max_length=256)
    """Dev mode 可省;DB mode 必填。"""


def _db_engine(request: Request) -> object | None:
    """從 app.state 取 db engine(可能 None — dev mode)。"""
    return getattr(request.app.state, "db_engine", None)


@router.post("/auth/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    engine: Annotated[object | None, Depends(_db_engine)],
) -> RegisterResponse:
    if engine is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "registration requires DB (set ORION_DB_URL)",
        )
    try:
        async with db_session(engine) as session: # type: ignore[arg-type]
            try:
                user = await create_user(
                    session, username=body.username, password=body.password,
                )
            except IntegrityError as e:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"username {body.username!r} already exists",
                ) from e
    except HTTPException:
        raise
    except Exception as e: # noqa: BLE001
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, f"register failed: {e}",
        ) from e

    return RegisterResponse(user_id=user.id, username=user.username)


@router.post("/auth/login", response_model=LoginResponse)
async def login(
    body: LoginWithPasswordRequest,
    engine: Annotated[object | None, Depends(_db_engine)],
) -> LoginResponse:
    """登入。

    DB 模式(engine 設):必驗密碼,失敗 401。
    Dev 模式(engine None):任意 username 通過(向後兼容)。
    """
    if engine is None:
        # Dev fallback — 任意 username,user_id 用 uuid5 deterministic 算
        return issue_token(
            user_id=dev_user_id(body.username),
            username=body.username,
        )

    async with db_session(engine) as session: # type: ignore[arg-type]
        user = await authenticate(
            session, username=body.username, password=body.password,
        )
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "invalid username or password",
        )
    return issue_token(user_id=user.id, username=user.username)


@router.get("/me", response_model=MeResponse)
async def me(
    identity: Annotated[Identity, Depends(current_identity)],
) -> MeResponse:
    """回 current user 的 id + username(從 JWT claim 取,不打 DB)。"""
    return MeResponse(user_id=identity.user_id, username=identity.username)


# 向後相容:的 LoginRequest 仍可解(若 client 沒帶 password,fall through DB 模式 401)。
_ = LoginRequest
