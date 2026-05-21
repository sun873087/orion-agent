"""Pane role CRUD RPC。

跟 skill_handlers 結構平行。User-level role 落
`~/.orion/users/<u>/roles/<name>/ROLE.md`(SDK default)。
Bundled 唯讀,UI 顯示但不能編輯。
"""

from __future__ import annotations

import re
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from orion_sdk.roles.loader import (
    _bundled_roles,
    get_user_roles_dir,
    load_roles_dir,
)

from orion_cowork_sidecar.storage import LOCAL_USER_ID


def _user_roles_dir() -> Path:
    return get_user_roles_dir(LOCAL_USER_ID)


def _slugify(name: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", name).strip().lower()
    slug = re.sub(r"[\s-]+", "-", slug)[:50]
    return slug or "role"


def _label_source(path: Path) -> str:
    p = str(path)
    if "/roles/bundled/" in p:
        return "bundled"
    if str(_user_roles_dir()) in p:
        return "user"
    return "other"


def _role_to_dict(role: Any) -> dict[str, Any]:
    source = _label_source(role.source_path) if role.source_path else "unknown"
    sp = role.source_path
    filename = sp.parent.name if sp and sp.name == "ROLE.md" else (sp.stem if sp else role.name)
    return {
        "name": role.name,
        "description": role.description,
        "filename": filename,
        "source": source,
        "editable": source == "user",
        "source_path": str(sp) if sp else None,
        "default_disabled_tools": role.default_disabled_tools,
        "default_permission_mode": role.default_permission_mode,
    }


async def role_list(_params: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    """合併 bundled + user roles。User 覆蓋 bundled(同名 last-wins)。"""
    by_name: dict[str, Any] = {}
    for r in _bundled_roles():
        by_name[r.name] = r
    for r in load_roles_dir(_user_roles_dir()):
        by_name[r.name] = r
    items = list(by_name.values())
    items.sort(key=lambda r: r.name)
    yield {
        "event": "role_list",
        "data": {
            "user_roles_dir": str(_user_roles_dir()),
            "roles": [_role_to_dict(r) for r in items],
        },
        "final": True,
    }


async def role_get(params: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    """讀 single role(含 body)。Bundled 也可讀,只是 editable=False。"""
    name = params.get("name")
    if not isinstance(name, str) or not name:
        yield {"event": "error", "data": {"code": "BAD_PARAMS", "message": "name required"}, "final": True}
        return
    by_name: dict[str, Any] = {}
    for r in _bundled_roles():
        by_name[r.name] = r
    for r in load_roles_dir(_user_roles_dir()):
        by_name[r.name] = r
    role = by_name.get(name)
    if role is None:
        yield {"event": "error", "data": {"code": "NOT_FOUND"}, "final": True}
        return
    yield {
        "event": "role",
        "data": {
            **_role_to_dict(role),
            "body": role.body,
        },
        "final": True,
    }


async def role_write(params: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    """建 / 覆蓋 user-level role。
    Params:name, body, description?, default_disabled_tools?(csv), default_permission_mode?
    """
    name = params.get("name")
    body = params.get("body", "")
    if not isinstance(name, str) or not name:
        yield {"event": "error", "data": {"code": "BAD_PARAMS", "message": "name required"}, "final": True}
        return
    if not isinstance(body, str):
        yield {"event": "error", "data": {"code": "BAD_PARAMS", "message": "body must be string"}, "final": True}
        return
    slug = _slugify(name)
    description = str(params.get("description") or "")
    raw_disabled = params.get("default_disabled_tools")
    if isinstance(raw_disabled, list):
        disabled_str = ",".join(str(x).strip() for x in raw_disabled if str(x).strip())
    elif isinstance(raw_disabled, str):
        disabled_str = ",".join(t.strip() for t in raw_disabled.split(",") if t.strip())
    else:
        disabled_str = ""
    perm = params.get("default_permission_mode")
    if perm not in ("ask", "act", None, ""):
        perm = None
    target_dir = _user_roles_dir() / slug
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "ROLE.md"
    frontmatter_lines = ["---", f"name: {name}"]
    if description:
        frontmatter_lines.append(f"description: {description}")
    if disabled_str:
        frontmatter_lines.append(f"default_disabled_tools: {disabled_str}")
    if perm:
        frontmatter_lines.append(f"default_permission_mode: {perm}")
    frontmatter_lines.append("---")
    full = "\n".join(frontmatter_lines) + "\n\n" + body.strip() + "\n"
    try:
        target.write_text(full, encoding="utf-8")
    except OSError as e:
        yield {"event": "error", "data": {"code": "IO_ERROR", "message": str(e)}, "final": True}
        return
    yield {
        "event": "role_written",
        "data": {
            "name": name,
            "filename": slug,
            "source_path": str(target),
        },
        "final": True,
    }


async def role_delete(params: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    """刪 user-level role(bundled 不可刪)。"""
    filename = params.get("filename") or params.get("name")
    if not isinstance(filename, str) or not filename:
        yield {"event": "error", "data": {"code": "BAD_PARAMS"}, "final": True}
        return
    slug = _slugify(filename)
    target = _user_roles_dir() / slug
    if not target.exists():
        yield {"event": "error", "data": {"code": "NOT_FOUND",
            "message": f"user role {slug!r} not found(bundled cannot be deleted)"}, "final": True}
        return
    try:
        shutil.rmtree(target)
    except OSError as e:
        yield {"event": "error", "data": {"code": "IO_ERROR", "message": str(e)}, "final": True}
        return
    yield {
        "event": "role_deleted",
        "data": {"name": filename},
        "final": True,
    }
