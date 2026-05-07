"""內建 skill 列表 — Phase 8。

對應 TS skills/bundledSkills.ts。內建 skill 跟 user 自寫 skill 一樣 expose,
但寫死在程式碼,不掃 disk。
"""

from __future__ import annotations

from orion_agent.skills.loader import Skill

_BE_CONCISE_BODY = """\
You should respond as concisely as possible. Skip preamble, restating, or
summarizing. Answer in one sentence when possible.\
"""

_REVIEW_DIFF_BODY = """\
You are reviewing a code diff. For each change:

1. **Bugs / logic errors** — flag explicitly.
2. **Style** — only mention if non-trivial.
3. **Tests** — note missing test coverage.
4. **Security** — flag sensitive patterns (eval, shell injection, etc).

Be concise. Group findings by severity. End with one-line verdict.\
"""


def builtin_skills() -> list[Skill]:
    """回傳內建 skill list。"""
    return [
        Skill(
            name="be-concise",
            description="Force concise responses (no preamble, no summary).",
            body=_BE_CONCISE_BODY,
        ),
        Skill(
            name="review-diff",
            description="Review a code diff for bugs / style / tests / security.",
            body=_REVIEW_DIFF_BODY,
            parameters={
                "type": "object",
                "properties": {
                    "diff": {
                        "type": "string",
                        "description": "The unified diff text to review.",
                    },
                },
                "required": ["diff"],
            },
        ),
    ]
