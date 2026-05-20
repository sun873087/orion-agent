"""/me/settings。Web chat 跨機器設定同步(REST CRUD)。

spec § 5.2 web chat 簡化版 — 不做 diff push / merge / conflict,直接 DB CRUD +
**樂觀鎖**(`version` 欄位)防多 tab race。

設計:
- GET /me/settings → 全部 settings(dict[str, Any])
- GET /me/settings/{key} → 單一(含 version)
- PUT /me/settings/{key} → 設(body 帶 expected_version → 不符 409)
- DELETE /me/settings/{key} → 刪(idempotent,不存在仍 200)

所有 endpoint JWT-protected,需 `ORION_DB_URL`。前端要實作:
1. PUT 時帶上次 GET 拿到的 version
2. 收 409 → 重 GET → 提示 user merge
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from orion_chat_api.deps import current_user
from orion_sdk.storage.db.engine import db_session
from orion_sdk.storage.db.models import UserSetting

router = APIRouter()


class SettingValue(BaseModel):
    """單筆 setting 的回應 / 請求 body。"""

    key: str
    value: Any
    version: int


class SettingPutBody(BaseModel):
    value: Any
    expected_version: int | None = None
    """前端帶上次 GET 的 version;不符 → 409。None → 不檢查(覆蓋)。"""


async def _require_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    engine = getattr(request.app.state, "db_engine", None)
    if engine is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "User settings require ORION_DB_URL to be set.",
        )
    async with db_session(engine) as session:
        yield session


@router.get("/me/settings")
async def get_all_settings(
    user_id: Annotated[str, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(_require_db)],
) -> dict[str, Any]:
    """回 user 全部 settings 為 dict[key -> value](不含 version)。

    若 client 需要 version(做樂觀鎖),改打單筆 GET。
    """
    rows = (
        await db.execute(
            select(UserSetting).where(UserSetting.user_id == user_id),
        )
    ).scalars().all()
    return {row.key: row.value for row in rows}


@router.get("/me/settings/{key}", response_model=SettingValue)
async def get_one_setting(
    key: str,
    user_id: Annotated[str, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(_require_db)],
) -> SettingValue:
    row = (
        await db.execute(
            select(UserSetting).where(
                UserSetting.user_id == user_id,
                UserSetting.key == key,
            ),
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Setting {key!r} not found.")
    return SettingValue(key=row.key, value=row.value, version=row.version)


@router.put("/me/settings/{key}", response_model=SettingValue)
async def put_setting(
    key: str,
    body: SettingPutBody,
    user_id: Annotated[str, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(_require_db)],
) -> SettingValue:
    """新建或更新。expected_version 不符 → 409 Conflict。"""
    row = (
        await db.execute(
            select(UserSetting).where(
                UserSetting.user_id == user_id,
                UserSetting.key == key,
            ),
        )
    ).scalar_one_or_none()

    if row is None:
        # 新建
        row = UserSetting(
            user_id=user_id,
            key=key,
            value=body.value,
            version=1,
        )
        db.add(row)
    else:
        if (
            body.expected_version is not None
            and row.version != body.expected_version
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                (
                    f"Version conflict for {key!r}: "
                    f"expected {body.expected_version}, current {row.version}. "
                    "Refetch and retry."
                ),
            )
        row.value = body.value
        row.version += 1

    await db.commit()
    await db.refresh(row)
    return SettingValue(key=row.key, value=row.value, version=row.version)


@router.delete("/me/settings/{key}")
async def delete_setting(
    key: str,
    user_id: Annotated[str, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(_require_db)],
) -> dict[str, bool]:
    """刪除。idempotent — 不存在也回 200。"""
    row = (
        await db.execute(
            select(UserSetting).where(
                UserSetting.user_id == user_id,
                UserSetting.key == key,
            ),
        )
    ).scalar_one_or_none()
    if row is not None:
        await db.delete(row)
        await db.commit()
    return {"deleted": row is not None}
