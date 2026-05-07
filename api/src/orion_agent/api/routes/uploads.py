"""/uploads — Phase 11 file upload REST。

POST /uploads(multipart)→ 存到 ~/.orion/uploads/<user_id>/<id>.<ext>
GET /uploads → list user uploads
DELETE /uploads/{id} → 刪除

對應 spec § Phase 11 file upload(取代 TS @file ref)。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from orion_agent.api.deps import current_user
from orion_agent.input.upload import (
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
