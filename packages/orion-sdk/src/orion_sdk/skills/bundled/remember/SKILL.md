---
name: remember
description: Review the user's memory + instruction layers (auto-memory, custom instructions, instructions.md), propose promotions / cleanup / conflict resolution.
---

# Memory Review

Review the user's memory landscape across orion-agent's layers and produce a clear report of proposed changes, grouped by action type. **Do NOT apply changes** — present proposals for user approval.

## orion-agent's Memory / Instructions Layers

orion-agent has two parallel mechanisms depending on mode (the user may be running in either):

### Web chat mode(`orion serve` + UI)

- **Auto-memory** — `~/.orion/users/<user_id>/memory/MEMORY.md` plus any linked files in the same dir. Working notes the agent extracts during conversations (Phase 3).
- **User custom instructions** — DB-stored, edit via REST `GET/PUT /me/custom-instructions` (UI: Settings → Instructions tab → "About you"). Persists across all conversations for that account.
- **Conversation custom instructions** — DB-stored per session, edit via REST `GET/PUT /sessions/{sid}/custom-instructions` (UI: same panel → "This conversation context"). Single conversation only.

### CLI mode(`orion run`)

- **Auto-memory** — same `~/.orion/users/<user_id>/memory/MEMORY.md`. `--user-id` flag picks tenant; default `default`.
- **System instructions** — `~/.orion/instructions.md`. Loaded for every CLI session globally.
- **Project instructions** — `<cwd>/.orion/instructions.md`. Per-repo, commit alongside code.

## Steps

### 1. Detect the mode + gather all layers

Detect mode:

- If running in a session backed by `orion serve`(web chat WS),the conversation has DB-backed user/conversation instructions accessible via REST.
- If running via `orion run`(CLI),`<cwd>/.orion/instructions.md` and `~/.orion/instructions.md` are the relevant layers.

Read what applies:

- Auto-memory:`~/.orion/users/<user_id>/memory/MEMORY.md` and linked files (use Read; ls the dir first to find linked files).
- Web chat:`GET /me/custom-instructions` and (if a session is current)`GET /sessions/{sid}/custom-instructions`.
- CLI:`Read ~/.orion/instructions.md` and `Read <cwd>/.orion/instructions.md` (skip if missing — that's normal).

If `user_id` is unknown, ask the user. If no auto-memory exists yet, note it.

**Success criteria**: You have the contents of all relevant layers and can compare them.

### 2. Classify each auto-memory entry

For each substantive entry in auto-memory, determine the best destination based on the user's mode:

| Mode | Destination | What belongs there | Examples |
|---|---|---|---|
| Both | **Stay in auto-memory** | Working notes, temporary context, uncertain patterns | Session-specific observations |
| Web chat | **User custom instructions**(`/me/custom-instructions`)| Durable preferences applying across all conversations | "Be concise", "I'm a senior Python engineer", "always explain trade-offs" |
| Web chat | **Conversation custom instructions**(`/sessions/{sid}`)| Context for the current conversation only | "This conversation is reviewing the migration script" |
| CLI | **`~/.orion/instructions.md`**(system / global)| Personal preferences applying to all CLI sessions | Same kind of personal preferences as user custom instructions |
| CLI | **`<cwd>/.orion/instructions.md`**(project)| Repo-wide conventions for any contributor running CLI here | "use uv not pip", "API routes use kebab-case", "test command is `make test`" |

**Important distinctions:**

- Both layers contain **instructions for the agent**,not user preferences for external tools(editor theme, IDE keybindings, etc. don't belong in either).
- Workflow practices(PR conventions, merge strategies, branch naming)are ambiguous — ask the user whether they're personal or team-wide.
- When unsure, ask rather than guess.

**Success criteria**: Each entry has a proposed destination or is flagged as ambiguous.

### 3. Identify cleanup opportunities

Scan across all layers for:

- **Duplicates** — Auto-memory entries already captured in user / project / conversation instructions → propose removing from auto-memory.
- **Outdated** — Older instructions contradicted by newer auto-memory entries → propose updating.
- **Conflicts** — Contradictions between any two layers → propose resolution, noting which is more recent.
- **Stale conversation instructions** — Conversation-level instructions still pinned for finished sessions → propose clearing.

**Success criteria**: All cross-layer issues identified.

### 4. Present the report

Output a structured report grouped by action type:

1. **Promotions** — entries to move, with destination and rationale
2. **Cleanup** — duplicates, outdated entries, conflicts to resolve
3. **Ambiguous** — entries where you need the user's input
4. **No action needed** — brief note on entries that should stay put

If auto-memory is empty, say so and offer to review the instructions layers for cleanup instead.

**Success criteria**: User can review and approve/reject each proposal individually.

## Rules

- Present ALL proposals before making any changes.
- Do NOT modify files / DB without explicit user approval.
- Do NOT create new files unless the target doesn't exist yet.
- Ask about ambiguous entries — don't guess.
- For web chat mode, applying changes goes through REST PUT calls(with optimistic locking — pass the `version` from the GET);file-level changes don't apply there.
- For CLI mode, applying changes is straight Edit/Write tool calls on `instructions.md`.
