"""/roles — per-user role(pane persona)CRUD over fs。

Role 存 `~/.orion/users/<uid>/roles/<name>/ROLE.md`(SDK 慣例)。跟 skills 同一套
規則:list 帶 bundled 共用 role(唯讀),只有 user dir 的可改 / 刪。

Role schema 比 skill 窄:body(prompt addendum)+ default_disabled_tools +
default_permission_mode(ask / act)。
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Annotated, Literal

import frontmatter
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from orion_chat_api.deps import current_user
from orion_sdk.roles.loader import get_user_roles_dir, load_all_roles

router = APIRouter()

_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


def _safe_name(name: str) -> str:
    if name in (".", "..") or not _NAME_PATTERN.match(name):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Invalid role name {name!r}: must match [A-Za-z0-9._-]+ "
            "(no path separators).",
        )
    return name


def _is_editable(source_path: Path | None, user_dir: Path) -> bool:
    if source_path is None:
        return False
    try:
        return source_path.resolve().is_relative_to(user_dir.resolve())
    except (OSError, ValueError):
        return False


class RoleSummary(BaseModel):
    name: str
    description: str
    default_disabled_tools: list[str] = Field(default_factory=list)
    default_permission_mode: Literal["ask", "act"] | None = None
    editable: bool


class RoleDetail(RoleSummary):
    body: str


class RoleWriteBody(BaseModel):
    description: str = Field(default="", max_length=2_000)
    body: str = Field(default="", max_length=200_000)
    default_disabled_tools: list[str] = Field(default_factory=list)
    default_permission_mode: Literal["ask", "act"] | None = None


@router.get("/roles", response_model=list[RoleSummary])
async def list_roles(
    user_id: Annotated[str, Depends(current_user)],
) -> list[RoleSummary]:
    user_dir = get_user_roles_dir(user_id)
    roles = load_all_roles(user_id=user_id)
    return [
        RoleSummary(
            name=r.name,
            description=r.description,
            default_disabled_tools=r.default_disabled_tools,
            default_permission_mode=_norm_mode(r.default_permission_mode),
            editable=_is_editable(r.source_path, user_dir),
        )
        for r in sorted(roles, key=lambda r: r.name.lower())
    ]


@router.get("/roles/{name}", response_model=RoleDetail)
async def get_role(
    name: str,
    user_id: Annotated[str, Depends(current_user)],
) -> RoleDetail:
    safe = _safe_name(name)
    user_dir = get_user_roles_dir(user_id)
    role = next((r for r in load_all_roles(user_id=user_id) if r.name == safe), None)
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Role {safe!r} not found.")
    return RoleDetail(
        name=role.name,
        description=role.description,
        body=role.body,
        default_disabled_tools=role.default_disabled_tools,
        default_permission_mode=_norm_mode(role.default_permission_mode),
        editable=_is_editable(role.source_path, user_dir),
    )


@router.put("/roles/{name}", response_model=RoleDetail)
async def put_role(
    name: str,
    body: RoleWriteBody,
    user_id: Annotated[str, Depends(current_user)],
) -> RoleDetail:
    safe = _safe_name(name)
    user_dir = get_user_roles_dir(user_id)
    role_dir = user_dir / safe
    md_path = role_dir / "ROLE.md"

    if md_path.is_file():
        post = frontmatter.load(str(md_path))
    else:
        post = frontmatter.Post("")
    post.metadata["name"] = safe
    post.metadata["description"] = body.description
    post.metadata["default_disabled_tools"] = body.default_disabled_tools
    if body.default_permission_mode is not None:
        post.metadata["default_permission_mode"] = body.default_permission_mode
    else:
        post.metadata.pop("default_permission_mode", None)
    post.content = body.body

    role_dir.mkdir(parents=True, exist_ok=True)
    md_path.write_text(frontmatter.dumps(post), encoding="utf-8")

    return RoleDetail(
        name=safe,
        description=body.description,
        body=body.body,
        default_disabled_tools=body.default_disabled_tools,
        default_permission_mode=body.default_permission_mode,
        editable=True,
    )


@router.delete("/roles/{name}")
async def delete_role(
    name: str,
    user_id: Annotated[str, Depends(current_user)],
) -> dict[str, bool]:
    safe = _safe_name(name)
    user_dir = get_user_roles_dir(user_id)
    role_dir = user_dir / safe
    flat = user_dir / f"{safe}.md"
    if (role_dir / "ROLE.md").is_file():
        shutil.rmtree(role_dir, ignore_errors=True)
        return {"deleted": True}
    if flat.is_file():
        flat.unlink()
        return {"deleted": True}
    return {"deleted": False}


def _norm_mode(mode: str | None) -> Literal["ask", "act"] | None:
    return mode if mode in ("ask", "act") else None
