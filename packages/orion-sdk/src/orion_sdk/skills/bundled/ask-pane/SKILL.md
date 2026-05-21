---
name: ask-pane
description: Query another pane (agent) in the same multi-pane collaboration window — read their recent transcript, current action, and partial output. Non-blocking. Use when the user says things like "see what @reviewer thought", "did @backend-coder finish the API?", or when your work depends on another pane's output. Requires this session to be part of a collaboration (auto-loaded by Cowork when collaboration is active).
cowork_visible: true
---

# /ask-pane — cross-pane query in a collaboration

Multi-pane collaboration runs N panes in one window, each is an independent
agent with its own conversation, model, and persona. From your pane you can
inspect what another pane is doing or has done — without interrupting them.

The actual data fetch is the `AskPane` tool. This skill teaches you when and
how to use it well.

---

## When to use AskPane

✅ User explicitly refers to another pane (`@reviewer thinks...`, `wait for @backend-coder`)
✅ Your work depends on output another pane is producing (you write client; they define API)
✅ User wants a synthesis (`compare what @coder-1 and @coder-2 came up with`)
✅ Sanity check before duplicating work (`@researcher already explored this, right?`)

❌ Just for curiosity / "small talk" — costs tokens, polluting context
❌ Repeatedly polling the same busy pane in a loop — you'll burn budget without info changing meaningfully
❌ Self-query (panes can't AskPane themselves — the tool refuses)

---

## How status semantics work

AskPane never blocks. It returns immediately with a `status`:

| status | meaning | how to react |
|---|---|---|
| `idle` | pane exists but has no messages yet | report that to user; suggest waiting or sending pane a prompt |
| `running` | pane is currently mid-stream (LLM thinking, tool running) | use `partial_output` if it's enough to continue, OR tell user the pane is busy and ask if they want to wait |
| `done` | pane finished its last turn | read `transcript_excerpt` and integrate |
| `not_found` | no pane with that name in this collaboration | check the system prompt's roster — you may have misspelled the name |
| `error` | something went wrong | surface error to user verbatim |

**Don't busy-poll** `running` status. If you got `running` and decided to wait,
tell the user "I'll proceed with X for now; let me know when you want me to
check back on @pane".

---

## What you receive

```json
{
  "status": "done",
  "pane_name": "@reviewer",
  "pane_role": "reviewer",
  "current_action": null,
  "transcript_excerpt": [
    {"role": "user", "text": "review the auth changes"},
    {"role": "assistant", "text": "Looked at auth.py:42. Two concerns: ..."},
    ...
  ],
  "partial_output": null
}
```

`transcript_excerpt` is the **tail** of the other pane's conversation
(default 8 messages, configurable via `n_recent_messages`). For long debates,
read the whole excerpt before jumping to conclusions — context matters.

---

## Mid-stream (`running` + `partial_output`)

If you queried while the other pane was still streaming, you get the
assistant's text up to that point:

```json
{
  "status": "running",
  "pane_name": "@coder-1",
  "current_action": "streaming response...",
  "partial_output": "Looking at the existing impl, I think we should refactor by..."
}
```

Decide:
- **Partial is enough**: continue with what you have, **explicitly note** in
  your response that you used partial output ("@coder-1's preliminary direction
  is X — I'm going with that pending their full conclusion")
- **Partial is not enough**: tell the user, suggest they let @coder-1 finish

---

## Anti-patterns

- **Hallucinating about other panes** without calling AskPane. If you didn't
  call the tool, you don't know what the pane said. Don't fake it.
- **Restating the entire transcript_excerpt verbatim** to the user — synthesize
  it. Cite specific points; don't dump raw blocks.
- **Using AskPane as a substitute for the user telling you something**. If the
  user wanted you to know what @reviewer said, they probably will tell you
  themselves (or paste it). Use AskPane when you genuinely need the other
  pane's record because they're working in parallel.

---

## Usage

If user calls `/ask-pane` with no args:

```
Usage: /ask-pane <pane_name> [question]

Query another pane's recent activity. Examples:
  /ask-pane @reviewer
  /ask-pane @backend-coder "did you finalize the API contract?"
```

Then call the `AskPane` tool with the given `pane_name` (strip `@` if present
— the tool accepts either form).
