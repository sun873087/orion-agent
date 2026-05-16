"""Cowork memory CRUD RPC — 直接讀寫 user memory dir 的 .md 檔。

SDK auto_extract 也寫進同一個目錄,所以 UI 增刪改跟自動 extract 共用同一份。
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path
from typing import Any

from orion_sdk.memory.paths import user_memory_paths
from orion_sdk.memory.scan import (
    load_memory_file,
    scan_memory_dir,
)
from orion_sdk.memory.types import MemoryFrontmatter, MemoryType

from orion_cowork_sidecar.storage import LOCAL_USER_ID


def _paths():
    return user_memory_paths(LOCAL_USER_ID)


def _slugify(name: str) -> str:
    """產出檔名:type_短-名稱.md 內 user 給的 name 部分"""
    slug = re.sub(r"[^\w\s-]", "", name).strip().lower()
    slug = re.sub(r"[\s-]+", "-", slug)[:40]
    return slug or "memory"


def _render_md(fm: MemoryFrontmatter, body: str) -> str:
    """frontmatter + body → 完整 .md 內容。"""
    lines = ["---", f"name: {fm.name}", f"description: {fm.description}"]
    if fm.type is not None:
        lines.append(f"type: {fm.type.value}")
    if fm.expires_at is not None:
        lines.append(f"expires_at: {fm.expires_at.isoformat()}")
    lines.append("---")
    lines.append("")
    lines.append(body.rstrip())
    lines.append("")
    return "\n".join(lines)


def _memory_to_dict(m: Any) -> dict[str, Any]:
    return {
        "filename": m.filename,
        "name": m.name,
        "description": m.description,
        "type": m.type.value if m.type else None,
        "expires_at": m.expires_at.isoformat() if m.expires_at else None,
        "body": m.body,
    }


async def memory_list(_params: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    paths = _paths()
    paths.ensure_dirs()
    index = scan_memory_dir(paths, exclude_expired=False)
    # 用 type + name 排序方便瀏覽
    sorted_mems = sorted(
        index.memories,
        key=lambda m: ((m.type.value if m.type else "z"), m.name.lower()),
    )
    yield {
        "event": "memory_list",
        "data": {
            "memory_dir": str(paths.memory_dir),
            "memories": [
                {
                    "filename": m.filename,
                    "name": m.name,
                    "description": m.description,
                    "type": m.type.value if m.type else None,
                    "expires_at": m.expires_at.isoformat() if m.expires_at else None,
                }
                for m in sorted_mems
            ],
        },
        "final": True,
    }


async def memory_get(params: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    filename = params.get("filename")
    if not isinstance(filename, str) or not filename.endswith(".md"):
        yield {"event": "error", "data": {"code": "BAD_PARAMS"}, "final": True}
        return
    paths = _paths()
    path = paths.memory_file(filename)
    if not path.is_file():
        yield {"event": "error", "data": {"code": "NOT_FOUND"}, "final": True}
        return
    mem = load_memory_file(path)
    if mem is None:
        yield {"event": "error", "data": {"code": "PARSE_FAILED"}, "final": True}
        return
    yield {
        "event": "memory",
        "data": {"memory": _memory_to_dict(mem)},
        "final": True,
    }


async def memory_write(params: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    """新增或更新一筆 memory。

    params:
      - filename: 可選。沒給就用 name slug 生(同名衝突附 -2 / -3)
      - name: 必填
      - description: 必填
      - type: 必填 (user|feedback|project|reference)
      - body: 必填
      - expires_at: 可選 ISO date 字串
    """
    name = params.get("name")
    description = params.get("description")
    type_str = params.get("type")
    body = params.get("body")
    if not all(isinstance(x, str) and x.strip() for x in (name, description, type_str, body)):
        yield {"event": "error", "data": {"code": "BAD_PARAMS",
               "message": "name / description / type / body required"}, "final": True}
        return
    assert isinstance(name, str)
    assert isinstance(description, str)
    assert isinstance(type_str, str)
    assert isinstance(body, str)
    try:
        mtype = MemoryType(type_str)
    except ValueError:
        yield {"event": "error", "data": {"code": "BAD_PARAMS",
               "message": f"unknown type: {type_str}"}, "final": True}
        return
    expires: date | None = None
    expires_raw = params.get("expires_at")
    if isinstance(expires_raw, str) and expires_raw:
        try:
            expires = date.fromisoformat(expires_raw)
        except ValueError:
            yield {"event": "error", "data": {"code": "BAD_PARAMS",
                   "message": "expires_at must be ISO date"}, "final": True}
            return

    fm = MemoryFrontmatter(
        name=name.strip(),
        description=description.strip(),
        type=mtype,
        expires_at=expires,
    )
    paths = _paths()
    paths.ensure_dirs()

    # filename 解析
    filename = params.get("filename")
    if isinstance(filename, str) and filename:
        if not filename.endswith(".md"):
            filename = filename + ".md"
        # 防 ../ 等
        if "/" in filename or filename.startswith("."):
            yield {"event": "error", "data": {"code": "BAD_PARAMS",
                   "message": "filename invalid"}, "final": True}
            return
    else:
        slug = _slugify(name)
        filename = f"{mtype.value}_{slug}.md"
        # 同名衝突附序號
        candidate = paths.memory_file(filename)
        i = 2
        while candidate.exists():
            filename = f"{mtype.value}_{slug}-{i}.md"
            candidate = paths.memory_file(filename)
            i += 1

    path = paths.memory_file(filename)
    text = _render_md(fm, body)
    path.write_text(text, encoding="utf-8")

    mem = load_memory_file(path)
    yield {
        "event": "memory",
        "data": {"memory": _memory_to_dict(mem) if mem else None,
                 "filename": filename},
        "final": True,
    }


async def memory_delete(params: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    filename = params.get("filename")
    if not isinstance(filename, str) or not filename.endswith(".md"):
        yield {"event": "error", "data": {"code": "BAD_PARAMS"}, "final": True}
        return
    if "/" in filename or filename.startswith("."):
        yield {"event": "error", "data": {"code": "BAD_PARAMS"}, "final": True}
        return
    paths = _paths()
    path = paths.memory_file(filename)
    if not path.is_file():
        yield {"event": "error", "data": {"code": "NOT_FOUND"}, "final": True}
        return
    path.unlink()
    yield {"event": "memory_deleted", "data": {"filename": filename}, "final": True}
