"""Skill 載入 — Phase 8。

Skill = markdown 檔 + YAML frontmatter。對應 TS skills/loadSkillsDir.ts。

Frontmatter 欄位:
- `name`(預設用檔名 stem)
- `description`(送給模型當 tool description)
- `parameters`(JSON Schema dict;模型呼 skill 時要帶)
- `hooks`(list of hook def,同 settings.json 格式)
- `effort`(low / medium / high)— 給 reasoning model 用
- `model`(覆寫 LLM model)

來源優先序(後者覆蓋前者,last-wins):
1. builtin(`orion_agent.skills.builtin`)
2. `~/.orion/skills/`(全域)
3. `.orion/skills/`(專案 cwd)
4. `extra_dirs`(plugin 提供的)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import frontmatter

logger = logging.getLogger(__name__)

_MAX_FILE_BYTES = 200 * 1024


@dataclass
class Skill:
    """Loaded skill。"""

    name: str
    description: str = ""
    body: str = ""
    """markdown body — 送給模型當 system / user prompt。"""
    parameters: dict[str, Any] | None = None
    """JSON Schema for skill arguments(可選)。"""
    hooks: list[dict[str, Any]] = field(default_factory=list)
    """Frontmatter 內宣告的 hook 條目(等同 settings.json `hooks` 內單筆)。"""
    effort: str | None = None
    model: str | None = None
    source_path: Path | None = None
    """檔案來源(供 debug / log)。"""


def load_skills_dir(directory: Path) -> list[Skill]:
    """掃單一目錄,parse 所有 `*.md` 為 Skill。

    缺檔 / 損壞 frontmatter 略過(log warning)。
    """
    if not directory.exists() or not directory.is_dir():
        return []

    skills: list[Skill] = []
    for md_path in sorted(directory.glob("**/*.md")):
        if not md_path.is_file():
            continue
        try:
            size = md_path.stat().st_size
        except OSError:
            continue
        if size > _MAX_FILE_BYTES:
            logger.warning("skill %s too large (%d bytes) — skipping", md_path, size)
            continue
        try:
            post = frontmatter.load(md_path)
        except Exception as e:  # noqa: BLE001
            logger.warning("failed to parse skill %s: %s", md_path, e)
            continue

        meta = post.metadata or {}
        name = str(meta.get("name") or md_path.stem)
        try:
            skill = Skill(
                name=name,
                description=str(meta.get("description") or ""),
                body=post.content or "",
                parameters=meta.get("parameters"),
                hooks=meta.get("hooks") or [],
                effort=meta.get("effort"),
                model=meta.get("model"),
                source_path=md_path,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("failed to build skill from %s: %s", md_path, e)
            continue
        skills.append(skill)
    return skills


def _default_user_skills_dir() -> Path:
    return Path(os.environ.get("ORION_SKILLS_DIR", str(Path.home() / ".orion" / "skills")))


def _project_skills_dir() -> Path:
    return Path.cwd() / ".orion" / "skills"


def load_all_skills(extra_dirs: list[Path] | None = None) -> list[Skill]:
    """全部來源 → 合併 → last-wins(同名)。

    Args:
        extra_dirs: plugin / caller 額外提供的目錄(優先級最高)。
    """
    from orion_agent.skills.builtin import builtin_skills

    sources: list[Skill] = list(builtin_skills())
    sources += load_skills_dir(_default_user_skills_dir())
    sources += load_skills_dir(_project_skills_dir())
    for d in extra_dirs or []:
        sources += load_skills_dir(d)

    # last-wins by name
    by_name: dict[str, Skill] = {}
    for s in sources:
        by_name[s.name] = s
    return list(by_name.values())


def find_skill(name: str, extra_dirs: list[Path] | None = None) -> Skill | None:
    """便利 wrapper。"""
    for s in load_all_skills(extra_dirs=extra_dirs):
        if s.name == name:
            return s
    return None
