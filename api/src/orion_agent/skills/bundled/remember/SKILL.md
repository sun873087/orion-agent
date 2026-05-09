---
name: remember
description: Review auto-memory / CLAUDE.md / per-user memory layers and propose promotions, cleanups, and conflict resolutions.
---

# Memory Review

## Goal

Review the user's memory landscape and produce a clear report of proposed changes, grouped by action type. **Do NOT apply changes** — present proposals for user approval.

## Steps

### 1. Gather all memory layers

Read the following memory sources (use Read tool):

- `CLAUDE.md` from the project root (if exists) — project-wide conventions
- `CLAUDE.local.md` from the project root (if exists) — personal overrides
- Auto-memory: under `~/.orion/memory/<user_id>/MEMORY.md` plus the linked memory files
- (orion specific) any custom instructions saved via the web UI's Instructions panel

**Success criteria**: You have the contents of all memory layers and can compare them.

### 2. Classify each auto-memory entry

For each substantive entry in auto-memory, determine the best destination:

| Destination | What belongs there | Examples |
|---|---|---|
| **CLAUDE.md** | Project conventions and instructions for the agent that all contributors should follow | "use bun not npm", "API routes use kebab-case", "test command is bun test", "prefer functional style" |
| **CLAUDE.local.md** | Personal instructions for the agent specific to this user, not applicable to other contributors | "I prefer concise responses", "always explain trade-offs", "don't auto-commit", "run tests before committing" |
| **Stay in auto-memory** | Working notes, temporary context, or entries that don't clearly fit elsewhere | Session-specific observations, uncertain patterns |

**Important distinctions:**

- CLAUDE.md and CLAUDE.local.md contain instructions for the agent, not user preferences for external tools (editor theme, IDE keybindings, etc. don't belong in either).
- Workflow practices (PR conventions, merge strategies, branch naming) are ambiguous — ask the user whether they're personal or team-wide.
- When unsure, ask rather than guess.

**Success criteria**: Each entry has a proposed destination or is flagged as ambiguous.

### 3. Identify cleanup opportunities

Scan across all layers for:

- **Duplicates**: Auto-memory entries already captured in CLAUDE.md or CLAUDE.local.md → propose removing from auto-memory
- **Outdated**: CLAUDE.md or CLAUDE.local.md entries contradicted by newer auto-memory entries → propose updating the older layer
- **Conflicts**: Contradictions between any two layers → propose resolution, noting which is more recent

**Success criteria**: All cross-layer issues identified.

### 4. Present the report

Output a structured report grouped by action type:

1. **Promotions** — entries to move, with destination and rationale
2. **Cleanup** — duplicates, outdated entries, conflicts to resolve
3. **Ambiguous** — entries where you need the user's input on destination
4. **No action needed** — brief note on entries that should stay put

If auto-memory is empty, say so and offer to review CLAUDE.md for cleanup.

**Success criteria**: User can review and approve/reject each proposal individually.

## Rules

- Present ALL proposals before making any changes.
- Do NOT modify files without explicit user approval.
- Do NOT create new files unless the target doesn't exist yet.
- Ask about ambiguous entries — don't guess.
