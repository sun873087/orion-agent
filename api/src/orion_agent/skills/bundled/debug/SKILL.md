---
name: debug
description: Help the user debug an issue in their current orion-agent session by reading session transcript / logs.
---

# Debug Skill

Help the user debug an issue they're encountering in their current orion-agent session.

## Session Transcript Location

orion-agent persists each session as JSONL transcript at:

```
~/.orion/sessions/<session_id>/transcript.jsonl
```

Each line is one event (user message / assistant message / tool_use / tool_result / turn_complete). Tail the last few hundred lines to see what the session was doing recently — old sessions can be huge so don't read in full.

```bash
# tail last 200 lines of current session transcript
tail -n 200 ~/.orion/sessions/<session_id>/transcript.jsonl | jq -c
```

## Settings Locations

Remember that settings are layered:

- **System / global** — `~/.orion/settings.json` (admin defaults)
- **Project** — `<cwd>/.orion/settings.json` (CLI mode)
- **Per-user** — backend-managed via `/me/settings` REST API + DB row(`UserSetting` table)

Backend env vars that affect runtime:

- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` — provider keys
- `ORION_DB_URL` — Postgres / SQLite connection
- `ORION_PROVIDER`, `ORION_MODEL` — server-default model
- `ORION_LOG_FORMAT=json` — structured logs
- `ORION_DEBUG=1` — verbose log output

## Issue Description

If the user provided context, focus on that first. Otherwise read the recent transcript and look for:

- `error` events in the transcript
- Tool calls that returned `is_error: true`
- Patterns like "stop_reason=max_tokens" (truncated response)
- `terminal` events with reasons other than `natural_stop`

## Instructions

1. **Review the user's issue description** (if any).
2. **Read the recent transcript** for the affected session — focus on the last few turns and any tool results / errors.
3. **Check backend logs** if available — run:
   ```bash
   ps -axo pid=,etime=,command= | grep -E '(orion serve|uvicorn)' | grep -v grep
   ```
   to find the server process; the user can `tail -f` whatever log file uvicorn writes to.
4. **Explain what you found** in plain language.
5. **Suggest concrete fixes or next steps** — don't just describe the problem.

## Notes

- Don't spike RSS by reading huge transcripts in full — use `tail` / range reads.
- If the user can reproduce the issue, ask them to do it after enabling `ORION_DEBUG=1` for richer logs.
- For provider errors (401 from Anthropic / OpenAI): check `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` env are set on the server.
