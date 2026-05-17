---
name: goal
description: Drive the conversation toward a specific goal — agent self-iterates (plan → act → evaluate → continue or stop) until the goal is met or a hard limit hits. Use when the user says "keep going until X", "make it work", "/goal <objective>", or sets any condition-driven task that needs multiple rounds without manual prodding each round.
cowork_visible: true
---

# /goal — drive toward a target condition

You are now in **goal mode**. The user gave you an objective; your job is to
keep working on it round after round, **self-evaluating each round**, until the
goal is met (then stop and report) or a hard limit is hit (then pause and ask).

This skill is different from `/loop`:

| | `/loop` | `/goal`(this skill) |
|---|---|---|
| What triggers next round | fixed time (cron) | you decide — immediately if not done |
| When to stop | user cancels | **you stop** when target is met |
| Round-to-round | independent re-fires | continuous iteration in this conversation |

---

## Step 1 — Parse the goal

User's input shape: `/goal <objective>` or natural-language like
「把測試跑到全綠」/「找到並修掉 production 那個 race condition」.

Extract three things(write them down explicitly in your first reply,user
checks):

1. **Objective** — what is "done"? Phrase as a single sentence.
2. **Success criteria** — what concrete signal proves it? File contents,
   test exit code, build output, observed behavior. **If you can't name a
   signal, the goal is too vague — ask user to sharpen it before iterating.**
3. **Boundaries** — what's NOT in scope(prevent feature creep mid-goal)?
   Time / cost / scope guardrails.

If the user's goal is one of these problematic shapes,**don't start iterating
— ask first**:

- Vague subjective ("make it better") → ask for measurable criterion
- Open-ended exploration ("explore this codebase") → loop / interactive chat fits better
- Requires destructive ops you can't undo → confirm scope first

---

## Step 2 — Plan the first iteration

Before round 1,write down:

- The single next action you'll take(not 5 — one)
- What output it produces
- How that output moves you toward the success criterion

Use `TodoWrite` if the path involves 3+ distinct sub-steps. One-shot work
skips Todo.

---

## Step 3 — Iterate (the inner loop)

For each round:

1. **Act** — do the one planned action(call tools / write code / run tests / etc.)
2. **Self-evaluate** — explicitly answer:
   - **Goal met?** Compare current state against the success criterion you
     wrote in Step 1. Be honest. "Mostly works" ≠ met.
   - **Made progress?** If criterion not met, what observably changed since
     last round?
   - **Stuck?** Same error 2 rounds in a row,or output unchanged.
3. **Decide next move**:
   - ✅ Goal met → jump to Step 5
   - 📈 Made progress → next round
   - 🛑 Stuck → jump to Step 4 (ask user)
   - ⏳ Hit hard limit(see below)→ pause + report

---

## Step 4 — When to stop iterating and ask the user

**Hard pause(don't keep going alone)** when any of:

- **20 rounds** elapsed without hitting success criterion → user check-in
- **Same error / output 2 rounds in a row** → likely stuck,you need input
- **Cost grew >10x** what you'd estimate for a normal task → confirm budget
- **You need destructive op** not pre-authorized — confirm before running
- **You need information you don't have** — credentials,domain context,
  user judgment call

In all these,don't quit — **pause + report status + ask one specific question**.
Format:

```
⏸ Pausing(reason: <which trigger above>).

Progress so far:
- <one-line of what's done>
- <what's remaining>

Question for you: <specific,answerable in one sentence>
```

---

## Step 5 — When the goal is met

Stop. Report:

```
✅ Goal met after N rounds.

Success criterion: <quote from Step 1>
Evidence: <observed signal — test output / file content / etc.>

(Optional)Side effects worth noting: <files changed / commits / cost>
```

**Don't add scope.** "While I was at it I also fixed X" is feature creep — if
you noticed something important,name it as a follow-up,don't silently do it.

---

## Step 6 — Reporting cadence

Between rounds 1–5: brief one-line progress per round("Round 3:tests still
failing on `test_foo`,trying narrower mock").

Round 5+: every round include a `Status` line so user can interrupt cleanly:

```
Round 7 status: <what just happened> · <distance to goal in 1 sentence>
```

---

## Anti-patterns to avoid

- **Declaring success without checking** — re-run the criterion check,don't
  trust "should work now"
- **Silent scope expansion** — name new findings as follow-ups,don't silently
  fix
- **Stuck-loop denial** — if 2 rounds produced same error,**stop**,don't
  rerun hoping
- **Skipping evaluation** — every round must answer "goal met? y/n" explicitly,
  even if obvious

---

## Usage

If the user calls `/goal` with no input,show:

```
Usage: /goal <objective>

Drive the conversation toward a specific goal. I'll iterate(plan → act →
evaluate)until the goal is met or I hit a hard limit(20 rounds / stuck /
need your judgment).

Examples:
  /goal 把 packages/orion-sdk 的 pyright errors 全清乾淨
  /goal find and fix the race condition in scheduler.py
  /goal 把 CSV `~/data.csv` 的重複 row dedupe 完並寫回去
```

After parsing,go to Step 1.
