"""/skills — per-user skill CRUD over fs。

Skill 存 `~/.orion/users/<uid>/skills/<name>/SKILL.md`(SDK 慣例 layout)。
這層只包 REST 殼。list 會帶 bundled / system / project 共用 skill(唯讀,
`editable=False`),只有寫在 user dir 的才可改 / 刪。

寫入用 python-frontmatter round-trip,保留既有的進階欄位(parameters / hooks /
effort / model)— web 只編 description / body / cowork_visible。

Skill name = 資料夾名,限 `[A-Za-z0-9._-]+`(無路徑分隔)擋穿越。刪除只動 user
自己的目錄,絕不碰 bundled / system(它們在別的 root)。
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Annotated

import frontmatter
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from orion_chat_api.deps import current_user
from orion_sdk.skills.loader import (
    find_skill,
    get_user_skills_dir,
    load_all_skills,
)

router = APIRouter()

_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


def _safe_name(name: str) -> str:
    if name in (".", "..") or not _NAME_PATTERN.match(name):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Invalid skill name {name!r}: must match [A-Za-z0-9._-]+ "
            "(no path separators).",
        )
    return name


def _is_editable(source_path: Path | None, user_dir: Path) -> bool:
    """skill 是否寫在這個 user 自己的目錄(可改 / 刪)。"""
    if source_path is None:
        return False
    try:
        return source_path.resolve().is_relative_to(user_dir.resolve())
    except (OSError, ValueError):
        return False


class SkillSummary(BaseModel):
    name: str
    description: str
    cowork_visible: bool = True
    editable: bool


class SkillDetail(SkillSummary):
    body: str


class SkillWriteBody(BaseModel):
    description: str = Field(default="", max_length=2_000)
    body: str = Field(default="", max_length=200_000)
    cowork_visible: bool = True


@router.get("/skills", response_model=list[SkillSummary])
async def list_skills(
    user_id: Annotated[str, Depends(current_user)],
) -> list[SkillSummary]:
    user_dir = get_user_skills_dir(user_id)
    skills = load_all_skills(user_id=user_id)
    return [
        SkillSummary(
            name=s.name,
            description=s.description,
            cowork_visible=s.cowork_visible,
            editable=_is_editable(s.source_path, user_dir),
        )
        for s in sorted(skills, key=lambda s: s.name.lower())
    ]


@router.get("/skills/{name}", response_model=SkillDetail)
async def get_skill(
    name: str,
    user_id: Annotated[str, Depends(current_user)],
) -> SkillDetail:
    safe = _safe_name(name)
    skill = find_skill(safe, user_id=user_id)
    if skill is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Skill {safe!r} not found.")
    user_dir = get_user_skills_dir(user_id)
    return SkillDetail(
        name=skill.name,
        description=skill.description,
        body=skill.body,
        cowork_visible=skill.cowork_visible,
        editable=_is_editable(skill.source_path, user_dir),
    )


@router.put("/skills/{name}", response_model=SkillDetail)
async def put_skill(
    name: str,
    body: SkillWriteBody,
    user_id: Annotated[str, Depends(current_user)],
) -> SkillDetail:
    """新建 / 覆寫 user skill。同名 bundled/system skill 會被使用者版覆蓋(last-wins)。"""
    safe = _safe_name(name)
    user_dir = get_user_skills_dir(user_id)
    skill_dir = user_dir / safe
    md_path = skill_dir / "SKILL.md"

    # 保留既有進階欄位(parameters / hooks / effort / model)
    if md_path.is_file():
        post = frontmatter.load(str(md_path))
    else:
        post = frontmatter.Post("")
    post.metadata["name"] = safe
    post.metadata["description"] = body.description
    post.metadata["cowork_visible"] = body.cowork_visible
    post.content = body.body

    skill_dir.mkdir(parents=True, exist_ok=True)
    md_path.write_text(frontmatter.dumps(post), encoding="utf-8")

    return SkillDetail(
        name=safe,
        description=body.description,
        body=body.body,
        cowork_visible=body.cowork_visible,
        editable=True,
    )


@router.delete("/skills/{name}")
async def delete_skill(
    name: str,
    user_id: Annotated[str, Depends(current_user)],
) -> dict[str, bool]:
    """刪除 user 自己的 skill(idempotent)。只動 user dir,不碰 bundled / system。"""
    safe = _safe_name(name)
    user_dir = get_user_skills_dir(user_id)
    skill_dir = user_dir / safe
    flat = user_dir / f"{safe}.md"
    if (skill_dir / "SKILL.md").is_file():
        shutil.rmtree(skill_dir, ignore_errors=True)
        return {"deleted": True}
    if flat.is_file():
        flat.unlink()
        return {"deleted": True}
    return {"deleted": False}
