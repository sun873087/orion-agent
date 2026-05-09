"""SkillTool — 載入 skill(markdown 模板)。

Phase 8 改造:從 frontmatter loader 取(含內建 + ~/.orion/skills + .orion/skills),
而非直接讀檔。對外 schema 不變(skill_name 空 = 列出;有名稱 = 回該 skill 內容)。

skill 目錄可由 ORION_SKILLS_DIR 環境變數覆蓋(預設 ~/.orion/skills)。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from pydantic import Field

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput
from orion_agent.skills.loader import Skill, load_all_skills


class SkillInput(ToolInput):
    """SkillTool 的 input。"""

    skill_name: str = Field(
        default="",
        description="Skill name (without .md). Leave empty to list all available skills.",
    )
    args: str = Field(
        default="",
        description=(
            "Optional argument string forwarded to the skill (e.g. user instruction, "
            "interval, file paths). Appended at the end of the skill body as 'Arguments'."
        ),
    )


class SkillTool:
    name = "Skill"
    description = (
        "Load a reusable instruction template ('skill') from disk or builtins. "
        "Pass skill_name='foo' to load the named skill. "
        "Pass empty skill_name to list available skills. "
        "Use this when the user mentions a workflow you've encountered before."
    )
    input_schema = SkillInput

    async def call(
        self,
        input: SkillInput,
        ctx: AgentContext,
    ) -> AsyncIterator[ToolEvent]:
        skills: list[Skill] = load_all_skills(user_id=ctx.user_id or None)

        if not input.skill_name.strip():
            if not skills:
                yield TextEvent(text="(no skills available)")
                return
            lines = ["Available skills:"]
            for s in skills:
                desc = f" — {s.description}" if s.description else ""
                lines.append(f"  - {s.name}{desc}")
            yield TextEvent(text="\n".join(lines))
            return

        # 防 path traversal(早就由 loader 隔離了 disk path,但 name 仍要 sanity check)
        name = input.skill_name.strip()
        if "/" in name or name.startswith(".") or "\\" in name:
            yield ErrorEvent(message=f"invalid skill name: {name!r}")
            return

        match = next((s for s in skills if s.name == name), None)
        if match is None:
            available = sorted(s.name for s in skills)
            yield ErrorEvent(
                message=f"skill {name!r} not found. Available: {available}",
            )
            return

        out_lines: list[str] = [f"# Skill: {match.name}"]
        if match.description:
            out_lines.append(f"\n{match.description}")
        out_lines.append("")
        out_lines.append(match.body)
        args = input.args.strip()
        if args:
            out_lines.append("\n## Arguments\n")
            out_lines.append(args)
        yield TextEvent(text="\n".join(out_lines))

    def is_concurrency_safe(self, input: SkillInput) -> bool:  # noqa: ARG002
        return True

    def is_read_only(self, input: SkillInput) -> bool:  # noqa: ARG002
        return True

    def max_result_size_chars(self) -> int | float:
        return 200_000
