"""SkillTool — 載入 ~/.orion/skills/*.md 的「skill」(可重複用的指令模板)。

對應 TS Claude Code skills 系統。Phase 1 範圍:
- input.skill_name 空 / 缺 → 列出所有可用 skills
- input.skill_name 有 → 回該 skill .md 檔的內容

skill 目錄可由 ORION_SKILLS_DIR 環境變數覆蓋(預設 ~/.orion/skills)。
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

from pydantic import Field

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput

_DEFAULT_DIR = Path.home() / ".orion" / "skills"
_MAX_FILE_BYTES = 100 * 1024


def _skills_dir() -> Path:
    return Path(os.environ.get("ORION_SKILLS_DIR", str(_DEFAULT_DIR)))


class SkillInput(ToolInput):
    """SkillTool 的 input。"""

    skill_name: str = Field(
        default="",
        description="Skill name (without .md). Leave empty to list all available skills.",
    )


class SkillTool:
    name = "Skill"
    description = (
        "Load a reusable instruction template ('skill') from disk. "
        "Pass skill_name='foo' to load ~/.orion/skills/foo.md. "
        "Pass empty skill_name to list available skills. "
        "Use this when the user mentions a workflow you've encountered before."
    )
    input_schema = SkillInput

    async def call(
        self,
        input: SkillInput,
        ctx: AgentContext,  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        skills_dir = _skills_dir()

        if not skills_dir.exists():
            yield TextEvent(
                text=f"(no skills directory at {skills_dir} — set ORION_SKILLS_DIR or create it)"
            )
            return

        if not skills_dir.is_dir():
            yield ErrorEvent(message=f"{skills_dir} exists but is not a directory")
            return

        if not input.skill_name.strip():
            # list mode
            md_files = sorted(skills_dir.glob("*.md"))
            if not md_files:
                yield TextEvent(text=f"(no .md skills found in {skills_dir})")
                return
            lines = [f"Available skills in {skills_dir}:"]
            for p in md_files:
                lines.append(f"  - {p.stem}")
            yield TextEvent(text="\n".join(lines))
            return

        # specific skill
        # 防 path traversal
        name = input.skill_name.strip()
        if "/" in name or name.startswith(".") or "\\" in name:
            yield ErrorEvent(message=f"invalid skill name: {name!r}")
            return

        skill_path = skills_dir / f"{name}.md"
        if not skill_path.exists():
            available = sorted(p.stem for p in skills_dir.glob("*.md"))
            yield ErrorEvent(
                message=(
                    f"skill {name!r} not found at {skill_path}. "
                    f"Available: {available}"
                )
            )
            return

        if skill_path.stat().st_size > _MAX_FILE_BYTES:
            yield ErrorEvent(
                message=f"skill file too large: {skill_path.stat().st_size} bytes (max {_MAX_FILE_BYTES})"
            )
            return

        try:
            text = skill_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as e:
            yield ErrorEvent(message=f"failed to read {skill_path}: {e}")
            return

        yield TextEvent(text=f"# Skill: {name}\n\n{text}")

    def is_concurrency_safe(self, input: SkillInput) -> bool:  # noqa: ARG002
        return True  # 純讀

    def is_read_only(self, input: SkillInput) -> bool:  # noqa: ARG002
        return True

    def max_result_size_chars(self) -> int | float:
        return _MAX_FILE_BYTES
