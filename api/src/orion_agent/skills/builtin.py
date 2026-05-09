"""Bundled skills 入口 — 為 backwards-compat 留 builtin_skills() function。

實際內容已搬到 `orion_agent/skills/bundled/<name>/SKILL.md` 一個 skill 一個資料夾,
由 loader._bundled_skills() 透過 importlib.resources 讀取(支援 wheel / zip 安裝)。

舊呼叫 `builtin_skills()` 仍可用,內部就是 `_bundled_skills()` alias。
"""

from __future__ import annotations

from orion_agent.skills.loader import Skill, _bundled_skills


def builtin_skills() -> list[Skill]:
    """回傳 bundled skill list(從 `skills/bundled/` 子資料夾載入)。"""
    return _bundled_skills()


__all__ = ["builtin_skills"]
