"""/uploads file upload REST。

POST /uploads(multipart)→ 存到 ~/.orion/users/<user_id>/uploads/<id>.<ext>
GET /uploads → list user uploads(新 + legacy 路徑 union)
DELETE /uploads/{id} → 刪除(新 + legacy 路徑都會找)

對應 spec § file upload(取代 TS @file ref)。
起 disk layout 改為 `users/<user_id>/uploads/` 與 memory 對齊;舊位置
`<base>/uploads/<user_id>/` 仍可讀(legacy fallback)— 詳見 `input/upload.py` docstring。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from orion_chat_api.deps import current_user
from orion_cli.input.upload import (
    UploadTooLargeError,
    delete_upload,
    list_uploads,
    save_upload,
)

router = APIRouter()


class UploadSummary(BaseModel):
    upload_id: str
    filename: str
    size: int


@router.post("/uploads", response_model=UploadSummary, status_code=status.HTTP_201_CREATED)
async def upload_file(
    user_id: Annotated[str, Depends(current_user)],
    file: Annotated[UploadFile, File(...)],
) -> UploadSummary:
    """multipart/form-data 上傳。"""
    data = await file.read()
    try:
        rec = save_upload(
            user_id=user_id,
            filename=file.filename or "upload",
            data=data,
        )
    except UploadTooLargeError as e:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, str(e)) from e
    return UploadSummary(
        upload_id=rec.upload_id,
        filename=rec.filename,
        size=rec.size,
    )


@router.get("/uploads", response_model=list[UploadSummary])
async def list_user_uploads(
    user_id: Annotated[str, Depends(current_user)],
) -> list[UploadSummary]:
    return [
        UploadSummary(upload_id=r.upload_id, filename=r.filename, size=r.size)
        for r in list_uploads(user_id)
    ]


@router.delete("/uploads/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_upload(
    upload_id: str,
    user_id: Annotated[str, Depends(current_user)],
) -> None:
    if not delete_upload(user_id, upload_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "upload not found")
