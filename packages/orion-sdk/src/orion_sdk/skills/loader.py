"""Skill 載入 —(+ 多租戶調整 + bundled folder convention)。

Skill = markdown 檔 + YAML frontmatter。對應 TS skills/loadSkillsDir.ts。

**目錄慣例**(對齊上游):
```
skills/
└── <skill-name>/
    └── SKILL.md ← 主 skill 檔(必)
    ├── examples/... ← 任何附加資料(可選,model 用 Read 取)
    └── ...
```

Frontmatter 欄位:
- `name`(預設用資料夾名)
- `description`(送給模型當 tool description)
- `parameters`(JSON Schema dict;模型呼 skill 時要帶)
- `hooks`(list of hook def,同 settings.json 格式)
- `effort`(low / medium / high)
- `model`(覆寫 LLM model)

來源優先序(後者覆蓋前者,last-wins):
1. **bundled**(`api/src/orion_agent/skills/bundled/`)— 套件附,跟著 pip install 一起來
2. **system**(`~/.orion/skills/`,env `ORION_SKILLS_DIR`)— admin 加的
3. project(`<cwd>/.orion/skills/`)— CLI 模式
4. **user**(`~/.orion/users/<user_id>/skills/`,env `ORION_USER_SKILLS_DIR`)— per-tenant
5. extra_dirs(plugin / caller 提供)— 最高優先

backwards-compat:flat top-level `*.md` 仍會載入(預設用檔名 stem 當 name)。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from importlib.resources import as_file, files
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
    hooks: list[dict[str, Any]] = field(default_factory=list)
    effort: str | None = None
    model: str | None = None
    cowork_visible: bool = True
    """Cowork 桌面 chat UI 的 slash popover 是否顯示這個 skill。
    `False` 時 LLM 仍可透過 Skill tool 用名字載入,只是 user-facing popover 隱藏 —
    用於「CLI 重度工作流」(譬如 `batch` 開多 worktree)在桌面 chat 場景沒意義的 skill。
    其他 host(CLI / chat-api)忽略此欄,一視同仁。"""
    source_path: Path | None = None
    """檔案來源(供 debug / log)。"""


def _parse_skill_md(md_path: Path, default_name: str) -> Skill | None:
    """Parse 一個 markdown(SKILL.md 或 flat .md)成 Skill。失敗回 None。"""
    try:
        size = md_path.stat().st_size
    except OSError:
        return None
    if size > _MAX_FILE_BYTES:
        logger.warning("skill %s too large (%d bytes) — skipping", md_path, size)
        return None
    try:
        post = frontmatter.load(md_path)
    except Exception as e: # noqa: BLE001
        logger.warning("failed to parse skill %s: %s", md_path, e)
        return None

    meta = post.metadata or {}
    name = str(meta.get("name") or default_name)
    cowork_visible_raw = meta.get("cowork_visible", True)
    cowork_visible = bool(cowork_visible_raw) if cowork_visible_raw is not None else True
    try:
        return Skill(
            name=name,
            description=str(meta.get("description") or ""),
            body=post.content or "",
            parameters=meta.get("parameters"),
            hooks=meta.get("hooks") or [],
            effort=meta.get("effort"),
            model=meta.get("model"),
            cowork_visible=cowork_visible,
            source_path=md_path,
        )
    except Exception as e: # noqa: BLE001
        logger.warning("failed to build skill from %s: %s", md_path, e)
        return None


def load_skills_dir(directory: Path) -> list[Skill]:
    """掃單一目錄,parse skill。

    支援兩種 layout(同上游慣例 + backwards-compat):

    - **慣例**:`<dir>/<name>/SKILL.md`(folder name = skill name)
    - **舊式**:`<dir>/<name>.md`(flat)

    缺檔 / 損壞 frontmatter 略過(log warning)。
    """
    if not directory.exists() or not directory.is_dir():
        return []

    skills: list[Skill] = []

    # 慣例:子資料夾 + SKILL.md
    for sub in sorted(directory.iterdir()):
        if not sub.is_dir():
            continue
        skill_md = sub / "SKILL.md"
        if not skill_md.is_file():
            continue
        skill = _parse_skill_md(skill_md, default_name=sub.name)
        if skill is not None:
            skills.append(skill)

    # backwards-compat:flat top-level *.md(不含子資料夾)
    # 排除 SKILL.md(屬於慣例 layout)+ README.md(說明文件,不是 skill)
    _SKIP_FLAT = {"SKILL.md", "README.md"}
    for md_path in sorted(directory.glob("*.md")):
        if not md_path.is_file() or md_path.name in _SKIP_FLAT:
            continue
        skill = _parse_skill_md(md_path, default_name=md_path.stem)
        if skill is not None:
            skills.append(skill)

    return skills


def _bundled_skills() -> list[Skill]:
    """從 package data 載入 bundled skills(`orion_agent/skills/bundled/`)。

    用 importlib.resources 確保安裝為 zip / wheel 也能讀。
    """
    try:
        bundled_root = files("orion_sdk.skills") / "bundled"
    except (ModuleNotFoundError, FileNotFoundError):
        return []

    # importlib.resources 不保證是 real path(zip 安裝會是 abstract Resource)
    # — as_file 把它 materialize 成可讀檔/dir
    try:
        with as_file(bundled_root) as real_path:
            return load_skills_dir(Path(real_path))
    except (FileNotFoundError, NotADirectoryError):
        return []


def _system_skills_dir() -> Path:
    """Server-level 共用 skills(admin 給所有 tenant 用)。"""
    return Path(
        os.environ.get("ORION_SKILLS_DIR", str(Path.home() / ".orion" / "skills")),
    )


def _user_skills_root() -> Path:
    """per-user skill 根目錄 — 各 tenant 一個子資料夾。

    預設 `~/.orion/users/`,可由 `ORION_USER_SKILLS_DIR` 覆蓋(整批根目錄)。
    """
    return Path(
        os.environ.get(
            "ORION_USER_SKILLS_DIR", str(Path.home() / ".orion" / "users"),
        ),
    )


def _user_skills_dir(user_id: str) -> Path:
    """單一 tenant 的 skills 目錄。"""
    safe = user_id.replace("/", "_").replace("\\", "_").lstrip(".")
    return _user_skills_root() / safe / "skills"


def get_user_skills_dir(user_id: str) -> Path:
    """Public — 給 host(chat-api RPC / route)寫 / 刪 skill 用。對齊 roles 的 get_user_roles_dir。"""
    return _user_skills_dir(user_id)


def _project_skills_dir() -> Path:
    """CLI cwd-based skills(web chat 場景 cwd 是 server 共用,效果等同 system 級)。"""
    return Path.cwd() / ".orion" / "skills"


def load_all_skills(
    extra_dirs: list[Path] | None = None,
    user_id: str | None = None,
) -> list[Skill]:
    """全部來源 → 合併 → last-wins(同名)。

    Args:
        extra_dirs: plugin / caller 額外提供的目錄(優先級最高)。
        user_id: 載入該 tenant 的 per-user skills。None → 跳過 user dir。
    """
    sources: list[Skill] = list(_bundled_skills())
    sources += load_skills_dir(_system_skills_dir())
    sources += load_skills_dir(_project_skills_dir())
    if user_id:
        sources += load_skills_dir(_user_skills_dir(user_id))
    for d in extra_dirs or []:
        sources += load_skills_dir(d)

    # last-wins by name
    by_name: dict[str, Skill] = {}
    for s in sources:
        by_name[s.name] = s
    return list(by_name.values())


def find_skill(
    name: str,
    extra_dirs: list[Path] | None = None,
    user_id: str | None = None,
) -> Skill | None:
    """便利 wrapper。"""
    for s in load_all_skills(extra_dirs=extra_dirs, user_id=user_id):
        if s.name == name:
            return s
    return None
