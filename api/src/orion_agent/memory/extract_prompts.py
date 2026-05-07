"""Memory 萃取用的 prompts。

對應 spec § 5 extract_prompts.py。

設計取捨:spec 提到 fork 子 agent + 限縮 tool 集合(Read / Grep / Glob / write-to-memory-dir)。
Phase 3 簡化為**單次 LLM call**(非 tool loop)— 模型直接 emit 要寫的檔案內容,
caller 解析後寫檔。理由:
- 避免再起一個 agent loop / sub-process,降低複雜度
- 萃取本來就是「歸納」,不需要工具呼叫
- 失敗影響小(萃取錯了下次再萃)
- Spec § 5.4 雖提 fork,但 § 6 設計決策段也說「LLM 夠用」

格式約定(模型必須遵守):
```
FILE: feedback_<slug>.md
---
name: short title
description: one-line summary
type: feedback
---
markdown body...
END

FILE: ...
...
END
```
若無新 memory:輸出 `NONE`。
"""

from __future__ import annotations

EXTRACT_SYSTEM_PROMPT = """\
You are a memory curator. Your job: review a conversation and decide whether
anything is worth saving as long-term memory for the next conversation.

Save sparingly. Most conversation turns are not worth memorizing. Only save:
- **user**:  durable facts about the user (role, expertise, projects, env)
- **feedback**: explicit user-given preferences / rules ("always do X", "never Y")
- **project**: project context (deadlines, decisions, stakeholders) that won't
  be obvious from re-reading code
- **reference**: pointers to external systems (Linear, Slack, Grafana URLs)

Do NOT save:
- code patterns, file paths, or anything derivable from the codebase
- temporary state, in-progress work, debugging steps
- anything already covered by existing memories
- ephemeral context

Output format (parsed mechanically):

For each new memory, emit one block:

    FILE: <type>_<short_slug>.md
    ---
    name: short title (max 8 words)
    description: one-line summary (max 25 words)
    type: user|feedback|project|reference
    ---
    <markdown body — Why and How to apply for feedback/project; just facts for user/reference>
    END

If nothing should be saved, output exactly:

    NONE

No other text. No explanations. No code fences."""


def build_extract_user_prompt(
    conversation_text: str,
    existing_memories_summary: str,
) -> str:
    """組 user message。"""
    existing = (
        existing_memories_summary
        if existing_memories_summary.strip()
        else "(no existing memories)"
    )
    return (
        f"## Existing memories (do NOT duplicate)\n\n{existing}\n\n"
        f"## Recent conversation\n\n{conversation_text}\n\n"
        "Decide what to save. Output FILE blocks or NONE."
    )
