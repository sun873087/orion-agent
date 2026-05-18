---
name: agent
description: Spawn one or more parallel sub-agents to handle self-contained sub-tasks. Use when the user calls `/agent <task>`, when the request naturally decomposes into independent parallel investigations (read N files / probe N URLs / N reviewer perspectives), or when you'd otherwise burn many tool calls on exploration that doesn't need to live in the main conversation history.
cowork_visible: true
---

# /agent — fan out to sub-agents

You are being asked to delegate work to **sub-agents** via the `Agent` tool.
Each sub-agent runs an independent agent loop with its own focused context
and returns only a final summary — your main conversation stays clean.

---

## Step 1 — Check the Agent tool is available

If `Agent` is **not** in your registered tool list, stop and tell the user:

> Agent tool is disabled by default in Cowork. Open **Settings → 工具 → Agent**
> and enable it, then try again.

Don't try to simulate sub-agents with normal tool calls — that defeats the
isolation and parallelism that makes sub-agents worth using.

---

## Step 2 — Decide if delegating is actually worth it

Sub-agents cost **3-5×** the tokens of doing the work yourself, so only
delegate when:

✅ The work splits into **independent** parallel pieces(reading 3 files,
   probing 5 URLs, 3 reviewer perspectives on the same diff)
✅ Each piece is **self-contained** — task description carries enough context
   for a fresh agent that can't see this conversation
✅ The exploration would generate **many tool results** you don't want
   polluting the main conversation history

❌ Linear dependency(A's output decides what B does)— do it yourself
❌ Simple task one tool call would solve
❌ Needs cross-agent shared state(sub-agents can't talk to each other)
❌ Needs deep nesting — sub-agents **cannot** spawn further sub-agents
   (`sub_agent_depth >= 1` hard-deny)

If none of the ✅ apply, **don't use Agent**. Just answer directly.

---

## Step 3 — Compose self-contained task strings

Each sub-agent only sees its `task` string — it cannot read this
conversation. So every task must include:

1. **What** to investigate / produce(specific question or deliverable)
2. **Where** to look(paths, URLs, scope boundaries)
3. **How** to report back(format, length, key fields to include)
4. **What's out of scope**(so the sub-agent doesn't drift)

Bad:`"Look at the codebase"`  → too vague,sub-agent will wander
Good:`"Read packages/orion-sdk/src/orion_sdk/core/conversation.py and
       return a 5-bullet summary of: (1) Conversation dataclass fields,
       (2) what send() does, (3) how state_messages are persisted,
       (4) any TODO/FIXME comments, (5) integration points worth knowing.
       Do NOT read any other files."`

---

## Step 4 — Fan out in parallel

Emit **multiple `Agent` tool calls in the same assistant message** — the
runtime spawns them concurrently via anyio task group. Don't serialize
them across turns (defeats the parallelism).

```
Agent(task="...探 A...")
Agent(task="...探 B...")
Agent(task="...探 C...")
```

All three run at the same time. Each returns final text to you when done.

---

## Step 5 — Synthesize results

Once all sub-agents return, **integrate** their findings into one coherent
answer for the user. Don't just dump three blocks of text — pick what
matters, point out conflicts / gaps, propose next action.

If a sub-agent failed or returned something weird, name it explicitly:

> Sub-agent B reported it couldn't find the file — likely path changed.
> Worth a manual `git log` to confirm.

---

## Anti-patterns

- **Spawning sub-agents for trivial work**:`/agent 把 README 的 typo
  改掉` — just do it yourself
- **Linear chained sub-agents**:if you need B to depend on A's output,
  do them as sequential turns yourself, not as Agent calls
- **Vague tasks that need this conversation's context**:if the task
  string ends up being half this chat copy-pasted, you're doing it wrong —
  do the work yourself
- **Hoping the sub-agent reads the user's intent**:it can't; spell out
  the full task

---

## Usage

If user calls `/agent` with no args:

```
Usage: /agent <task description>

Spawn one or more sub-agents to handle parallel sub-tasks. I'll decide how
many to fan out based on whether the work splits into independent pieces.

Examples:
  /agent 讀 packages/orion-sdk/src/orion_sdk/core/ 內 5 個 .py 各別摘要
  /agent 分別從 security / performance / correctness 三個角度 review 這 PR
  /agent 爬 https://x.com / https://y.com / https://z.com 比較 pricing
```

After receiving the task, jump to Step 2 to evaluate, then proceed.
