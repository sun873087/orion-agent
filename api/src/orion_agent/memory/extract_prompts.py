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

UPDATE: feedback_existing.md
---
name: short title
description: one-line summary
type: feedback
---
merged markdown body...
END
```
若無新 memory:輸出 `NONE`。

`UPDATE` 用於擴充/修正既有 memory(避免重複建立),內容必須是合併後的完整檔案,
不是 patch。系統會 overwrite 對應檔案。
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
- ephemeral context

**Before emitting a new FILE block**, scan the existing-memories list. If your
finding overlaps an existing memory (same topic / same rule restated / same
project / same reference), emit `UPDATE: <filename>` instead — with the merged
content. Prefer updating to creating; duplicate memories make future retrieval
worse and inflate the memory directory.

**Optional `expires_at` field (ISO date, e.g. `2026-09-30`)** — sets a date
after which the memory stops being injected into prompts (the file is kept,
but treated as stale). Use it when the saved fact is inherently time-bound:
- **project**: set to the project's natural end (deadline, release date). If
  the conversation mentions a date, use that; otherwise pick ~90 days out.
- **reference**: set ~180 days out (URLs / external systems can rot).
- **user / feedback**: omit (these are durable; don't auto-expire).

Output format (parsed mechanically):

For a brand-new memory:

    FILE: <type>_<short_slug>.md
    ---
    name: short title (max 8 words)
    description: one-line summary (max 25 words)
    type: user|feedback|project|reference
    expires_at: <YYYY-MM-DD>          # optional; omit for durable memories
    ---
    <markdown body — Why and How to apply for feedback/project; just facts for user/reference>
    END

For updating an existing memory (use the filename shown in the existing list):

    UPDATE: <existing_filename>.md
    ---
    name: <updated or same>
    description: <updated or same>
    type: <same type>
    expires_at: <YYYY-MM-DD or omit>
    ---
    <full merged body — system overwrites the file with this>
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
        f"## Existing memories (prefer UPDATE over duplicate FILE)\n\n{existing}\n\n"
        f"## Recent conversation\n\n{conversation_text}\n\n"
        "Decide what to save. Output FILE / UPDATE blocks or NONE."
    )
