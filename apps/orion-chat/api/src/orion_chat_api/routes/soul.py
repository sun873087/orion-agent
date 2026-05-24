"""/me/soul — 永久人格 markdown 的讀 / 寫 / 清除(per-user)。

存 `~/.orion/users/<uid>/memory/soul.md`。寫入內容會在**下一個** session
(或 cache-miss rebuild)inject 進 system prompt 前綴 — 見 user_context.py。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from orion_chat_api.deps import current_user
from orion_chat_api.user_context import read_soul, write_soul

router = APIRouter()


class SoulBody(BaseModel):
    content: str = Field(default="", max_length=200_000)


class SoulResponse(BaseModel):
    content: str


@router.get("/me/soul", response_model=SoulResponse)
async def get_soul(
    user_id: Annotated[str, Depends(current_user)],
) -> SoulResponse:
    return SoulResponse(content=read_soul(user_id))


@router.put("/me/soul", response_model=SoulResponse)
async def put_soul(
    body: SoulBody,
    user_id: Annotated[str, Depends(current_user)],
) -> SoulResponse:
    """寫入(空內容 = 清除)。回傳正規化後的內容。"""
    write_soul(body.content, user_id)
    return SoulResponse(content=read_soul(user_id))


@router.delete("/me/soul", response_model=SoulResponse)
async def delete_soul(
    user_id: Annotated[str, Depends(current_user)],
) -> SoulResponse:
    """清除 soul(idempotent)。"""
    write_soul("", user_id)
    return SoulResponse(content="")
