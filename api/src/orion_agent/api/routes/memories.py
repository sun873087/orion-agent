"""/me/memories — Phase 25。Memory CRUD over fs(per-user)。

Memory 仍存 `~/.orion/users/<uid>/memory/*.md`(Phase 3 既有 layout),這層只包
REST 殼讓 web UI 能 list / read / write / delete。**沒搬 DB** — Phase 3 設計就是
fs-based,搬 DB 是另一個 phase 的事。

Frontmatter 格式由 `memory.scan.parse_frontmatter` 處理。寫入時我們重組 KEY: VALUE
三行 + body,再讓 scan layer 重新 parse 驗證 round-trip。

Filename 安全:只接受 `[A-Za-z0-9._-]+\\.md`(無路徑分隔、無 `..`),否則 422 —
擋路徑穿越攻擊(user 雖然只能寫自己 dir,但仍要避免寫到 dir 外其他 user 檔)。
"""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from orion_agent.api.deps import current_user
from orion_agent.memory.paths import user_memory_paths
from orion_agent.memory.scan import (
    load_memory_file,
    parse_frontmatter,
    scan_memory_dir,
    write_index,
)
from orion_agent.memory.types import MemoryType

router = APIRouter()


_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+\.md$")


class MemorySummary(BaseModel):
    """list endpoint 的單筆;不含 body 省 payload。"""

    filename: str
    name: str
    description: str
    type: MemoryType | None = None


class MemoryDetail(MemorySummary):
    """單筆完整(含 body)。"""

    body: str


class MemoryWriteBody(BaseModel):
    """PUT body — frontmatter 欄位 + body。"""

    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=500)
    type: MemoryType | None = None
    body: str = Field(default="", max_length=200_000)
    """memory 內容(markdown)。允許空。"""


def _safe_filename(filename: str) -> str:
    """驗 filename;失敗 raise 422。"""
    if not _FILENAME_PATTERN.match(filename):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            (
                f"Invalid filename {filename!r}: must match "
                "[A-Za-z0-9._-]+.md (no path separators, no '..')."
            ),
        )
    if filename == "MEMORY.md":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "MEMORY.md is the index file and cannot be edited via REST.",
        )
    return filename


def _render_memory_file(body: MemoryWriteBody) -> str:
    """將 body 重組為 .md 檔內容(frontmatter + body)。"""
    type_line = f"type: {body.type.value}\n" if body.type is not None else ""
    return (
        "---\n"
        f"name: {body.name}\n"
        f"description: {body.description}\n"
        f"{type_line}"
        "---\n"
        f"{body.body}"
    )


def _rewrite_index(user_id: str) -> None:
    """rescan + 重寫 MEMORY.md。寫操作後呼叫。"""
    paths = user_memory_paths(user_id)
    paths.ensure_dirs()
    index = scan_memory_dir(paths)
    write_index(paths, index.memories)


@router.get("/me/memories", response_model=list[MemorySummary])
async def list_memories(
    user_id: Annotated[str, Depends(current_user)],
) -> list[MemorySummary]:
    """列 user 全部 memory(不含 body,按 filename 排序)。"""
    paths = user_memory_paths(user_id)
    index = scan_memory_dir(paths)
    return [
        MemorySummary(
            filename=m.filename,
            name=m.name,
            description=m.description,
            type=m.type,
        )
        for m in index.memories
    ]


@router.get("/me/memories/{filename}", response_model=MemoryDetail)
async def get_memory(
    filename: str,
    user_id: Annotated[str, Depends(current_user)],
) -> MemoryDetail:
    fname = _safe_filename(filename)
    paths = user_memory_paths(user_id)
    path = paths.memory_file(fname)
    mem = load_memory_file(path)
    if mem is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Memory {fname!r} not found.")
    return MemoryDetail(
        filename=mem.filename,
        name=mem.name,
        description=mem.description,
        type=mem.type,
        body=mem.body,
    )


@router.put("/me/memories/{filename}", response_model=MemoryDetail)
async def put_memory(
    filename: str,
    body: MemoryWriteBody,
    user_id: Annotated[str, Depends(current_user)],
) -> MemoryDetail:
    """新建或覆蓋 memory。寫完 rescan + 更新 MEMORY.md 索引。"""
    fname = _safe_filename(filename)
    paths = user_memory_paths(user_id)
    paths.ensure_dirs()

    text = _render_memory_file(body)

    # round-trip 驗證:確保寫入後 scan 能解出
    fm, _ = parse_frontmatter(text)
    if fm is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Frontmatter rendered from request would not parse — likely "
            "name/description contains a newline. Strip newlines and retry.",
        )

    path = paths.memory_file(fname)
    path.write_text(text, encoding="utf-8")
    _rewrite_index(user_id)

    return MemoryDetail(
        filename=fname,
        name=fm.name,
        description=fm.description,
        type=fm.type,
        body=body.body,
    )


@router.delete("/me/memories/{filename}")
async def delete_memory(
    filename: str,
    user_id: Annotated[str, Depends(current_user)],
) -> dict[str, bool]:
    """刪除。idempotent — 不存在仍 200。刪後重寫索引。"""
    fname = _safe_filename(filename)
    paths = user_memory_paths(user_id)
    path = paths.memory_file(fname)
    existed = path.exists()
    if existed:
        path.unlink()
        _rewrite_index(user_id)
    return {"deleted": existed}
