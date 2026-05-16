"""Cowork skill CRUD RPC。

User-level skill 落 `~/.orion-cowork/users/cowork-local/skills/<name>/SKILL.md`
(走 ORION_USERS_DIR env)。Bundled / system / project 是唯讀來源,UI 只能
看不能改。
"""

from __future__ import annotations

import re
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from orion_sdk.memory.paths import default_users_root
from orion_sdk.skills.loader import (
    _bundled_skills,
    _system_skills_dir,
    load_skills_dir,
)

from orion_cowork_sidecar.storage import LOCAL_USER_ID


def _user_skills_dir() -> Path:
    """Cowork 跑時 ORION_USERS_DIR 指 ~/.orion-cowork/users。"""
    return default_users_root() / LOCAL_USER_ID / "skills"


async def _project_skills_dir(project_id: str) -> Path | None:
    """<workspace>/.orion-cowork/skills/ 若 project 有 workspace。"""
    from orion_cowork_sidecar import storage as _storage
    engine = await _storage.init_storage()
    proj = await _storage.get_project(engine, project_id)
    if proj is None or not proj.workspace_dir:
        return None
    d = Path(proj.workspace_dir) / ".orion-cowork" / "skills"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slugify(name: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", name).strip().lower()
    slug = re.sub(r"[\s-]+", "-", slug)[:50]
    return slug or "skill"


def _label_source(path: Path) -> str:
    """分類 source。"""
    p = str(path)
    if "/skills/bundled/" in p:
        return "bundled"
    if str(_user_skills_dir()) in p:
        return "user"
    if str(_system_skills_dir()) in p:
        return "system"
    return "other"


def _skill_to_dict(skill: Any) -> dict[str, Any]:
    source = _label_source(skill.source_path) if skill.source_path else "unknown"
    # filename:user-level 我們用 folder name(== skill.name),其他來源也用 folder/檔名
    sp = skill.source_path
    filename = sp.parent.name if sp and sp.name == "SKILL.md" else (sp.stem if sp else skill.name)
    return {
        "name": skill.name,
        "description": skill.description,
        "filename": filename,
        "source": source,
        "editable": source == "user",
        "source_path": str(sp) if sp else None,
    }


async def skill_list(params: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    """有 project_id → 只列 project 的 skills(co-located in workspace)。
    沒 → 合併 bundled / system / user。
    """
    project_id = params.get("project_id") if isinstance(params.get("project_id"), str) else None
    if project_id:
        pdir = await _project_skills_dir(project_id)
        items = load_skills_dir(pdir) if pdir else []
        yield {
            "event": "skill_list",
            "data": {
                "user_skills_dir": str(pdir) if pdir else "",
                "skills": [_skill_to_dict(s) for s in items],
            },
            "final": True,
        }
        return
    by_name: dict[str, Any] = {}
    for skill in _bundled_skills():
        by_name[skill.name] = skill
    for skill in load_skills_dir(_system_skills_dir()):
        by_name[skill.name] = skill
    for skill in load_skills_dir(_user_skills_dir()):
        by_name[skill.name] = skill
    items = sorted(by_name.values(), key=lambda s: s.name.lower())
    yield {
        "event": "skill_list",
        "data": {
            "user_skills_dir": str(_user_skills_dir()),
            "skills": [_skill_to_dict(s) for s in items],
        },
        "final": True,
    }


async def skill_get(params: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    name = params.get("name")
    if not isinstance(name, str):
        yield {"event": "error", "data": {"code": "BAD_PARAMS"}, "final": True}
        return
    project_id = params.get("project_id") if isinstance(params.get("project_id"), str) else None
    by_name: dict[str, Any] = {}
    if project_id:
        pdir = await _project_skills_dir(project_id)
        if pdir:
            for skill in load_skills_dir(pdir):
                by_name[skill.name] = skill
    else:
        for skill in _bundled_skills():
            by_name[skill.name] = skill
        for skill in load_skills_dir(_system_skills_dir()):
            by_name[skill.name] = skill
        for skill in load_skills_dir(_user_skills_dir()):
            by_name[skill.name] = skill
    skill = by_name.get(name)
    if skill is None:
        yield {"event": "error", "data": {"code": "NOT_FOUND"}, "final": True}
        return
    yield {
        "event": "skill",
        "data": {
            "skill": {
                **_skill_to_dict(skill),
                "body": skill.body,
            },
        },
        "final": True,
    }


async def skill_write(params: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    """新增或更新 user-level skill。

    params:
      - filename: 可選(沒給用 slug from name)— 對應 folder name
      - name: 必填
      - description: 必填
      - body: 必填(markdown)
      - rename_from: 可選,改名時刪舊 folder
    """
    name = params.get("name")
    description = params.get("description")
    body = params.get("body")
    if not all(isinstance(x, str) and x.strip() for x in (name, description, body)):
        yield {"event": "error", "data": {"code": "BAD_PARAMS",
               "message": "name / description / body required"}, "final": True}
        return
    assert isinstance(name, str)
    assert isinstance(description, str)
    assert isinstance(body, str)

    project_id = params.get("project_id") if isinstance(params.get("project_id"), str) else None
    if project_id:
        pdir = await _project_skills_dir(project_id)
        if pdir is None:
            yield {"event": "error", "data": {"code": "NOT_FOUND",
                   "message": "project has no workspace"}, "final": True}
            return
        user_dir = pdir
    else:
        user_dir = _user_skills_dir()
        user_dir.mkdir(parents=True, exist_ok=True)

    filename = params.get("filename")
    if not isinstance(filename, str) or not filename:
        filename = _slugify(name)
    # 防 path injection
    if "/" in filename or filename.startswith("."):
        yield {"event": "error", "data": {"code": "BAD_PARAMS",
               "message": "filename invalid"}, "final": True}
        return

    # rename 處理
    rename_from = params.get("rename_from")
    if isinstance(rename_from, str) and rename_from and rename_from != filename:
        old_dir = user_dir / rename_from
        if old_dir.is_dir():
            shutil.rmtree(old_dir, ignore_errors=True)

    target_dir = user_dir / filename
    target_dir.mkdir(parents=True, exist_ok=True)
    md_path = target_dir / "SKILL.md"

    # 寫 frontmatter:用簡單 YAML(name / description),body 原樣
    content = (
        "---\n"
        f"name: {name.strip()}\n"
        f"description: {description.strip()}\n"
        "---\n\n"
        + body.rstrip() + "\n"
    )
    md_path.write_text(content, encoding="utf-8")

    yield {
        "event": "skill_written",
        "data": {"name": name.strip(), "filename": filename},
        "final": True,
    }


async def skill_delete(params: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    """刪 user-level 或 project-level skill(整個 folder)。"""
    filename = params.get("filename")
    if not isinstance(filename, str) or "/" in filename or filename.startswith("."):
        yield {"event": "error", "data": {"code": "BAD_PARAMS"}, "final": True}
        return
    project_id = params.get("project_id") if isinstance(params.get("project_id"), str) else None
    if project_id:
        pdir = await _project_skills_dir(project_id)
        if pdir is None:
            yield {"event": "error", "data": {"code": "NOT_FOUND"}, "final": True}
            return
        target = pdir / filename
    else:
        target = _user_skills_dir() / filename
    if not target.is_dir():
        yield {"event": "error", "data": {"code": "NOT_FOUND"}, "final": True}
        return
    shutil.rmtree(target, ignore_errors=True)
    yield {
        "event": "skill_deleted",
        "data": {"filename": filename},
        "final": True,
    }
