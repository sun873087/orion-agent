---
name: update-config
description: Update orion-agent settings — picks the right scope (system / project / per-user) and uses Config tool / REST endpoint to apply.
cowork_visible: false
---

# Update Config

Help the user change orion-agent settings safely. Pick the right scope, validate the value, and use the appropriate write path.

## Settings Layers

Settings load in this order; later overrides earlier:

| Layer | Path | Scope | How to write |
|------|------|-------|-------------|
| **System / global** | `~/.orion/settings.json` | All users / projects on this machine | `Config` tool with `action: "set"` (CLI only — touches admin file) |
| **Project** | `<cwd>/.orion/settings.json` | This project only | `Config` tool, run from project root |
| **Per-user** | DB `UserSetting` table | This account, across machines | `PUT /me/settings/<key>` REST endpoint with `expected_version` |

> Per-user settings (web chat scope) use **optimistic locking** — read, modify, PUT with `expected_version` from the read. Conflict → 409, refetch + retry.

## Settings Schema (orion-agent)

```json
{
  "permissions": {
    "rules": [
      { "tool": "BashTool", "decision": "always_allow" },
      { "tool": "FileWriteTool", "match": { "path": "/etc/*" }, "decision": "always_deny" }
    ]
  },
  "hooks": {
    "PreToolUse":  [ { "matcher": { "tool": "BashTool" }, "command": "..." } ],
    "PostToolUse": [],
    "SessionStart": []
  },
  "memory": {
    "enabled": true,
    "auto_extract": true
  },
  "preferred_provider": "anthropic",
  "preferred_model": "claude-sonnet-4-6",
  "theme": "dark",
  "telemetry": {
    "enabled": false,
    "otel_endpoint": "http://localhost:4317"
  }
}
```

(Not exhaustive — orion adds settings as new phases land.)

## Permission Rule Syntax

```json
{ "tool": "BashTool", "match": { "command": "git status" }, "decision": "always_allow" }
{ "tool": "FileWriteTool", "match": { "path": "/etc/*" }, "decision": "always_deny" }
{ "tool": "WebFetchTool", "decision": "always_allow" }
```

Match keys depend on tool. Use exact match or `*` glob in path. Order matters within `rules` — first match wins.

## Process

### 1. Identify what the user wants to change

- Tool permission?
- Hook (PreToolUse / PostToolUse)?
- Model preference?
- Memory toggle?
- Theme / cosmetic?

### 2. Pick the right layer

- Personal-only preference → per-user (REST `/me/settings`)
- Project-wide convention → project `.orion/settings.json` (commit it)
- Admin / cross-tenant → system `~/.orion/settings.json` (rare, admin only)

### 3. Read current value

- For file-based: `Read ~/.orion/settings.json` (or project version)
- For per-user: `GET /me/settings/<key>` to get value + version

### 4. Make the change

- File-based: use `Config` tool's `set` action (atomic write to settings.json)
- Per-user: `PUT /me/settings/<key>` with `expected_version` from step 3

### 5. Verify

- Re-read or re-GET the value
- If user changed model/theme, mention they need to start a new session to see effect

## Common Pitfalls

- **JSON syntax errors** — keep it simple, use the Config tool (it validates) rather than hand-editing.
- **Wrong layer** — if a user changes their personal preference in the project file, others on the team will see it. Always ask which scope.
- **Permission rules order** — first match wins. New `always_deny` won't override an earlier `always_allow` for the same tool.
- **Hooks shell command** — runs with the user's permissions on the server; never set hook commands the user can't audit.
