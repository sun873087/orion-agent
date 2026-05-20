"""Skills package。

Skill = markdown 檔(`.md`)+ YAML frontmatter,提供 prompt template + parameters
+ frontmatter hooks。

Public API:
- `Skill` model
- `load_skills_dir(directory)` 掃單一目錄
- `load_all_skills(extra_dirs=None)` 全部來源(內建 + 全域 + 專案 + plugin)
- `find_skill(name)` 取單一 skill(後者覆蓋前者,last-wins)
"""

from __future__ import annotations

from orion_sdk.skills.loader import (
    Skill,
    find_skill,
    load_all_skills,
    load_skills_dir,
)

__all__ = ["Skill", "find_skill", "load_all_skills", "load_skills_dir"]
