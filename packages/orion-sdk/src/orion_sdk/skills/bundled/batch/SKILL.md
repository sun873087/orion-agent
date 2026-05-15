---
name: batch
description: Research and plan a large-scale change, then execute it in parallel across 5-30 isolated worktree agents that each open a PR.
---

# Batch: Parallel Work Orchestration

You are orchestrating a large, parallelizable change across this codebase.

## Phase 1: Research and Plan (Plan Mode)

Call the EnterPlanMode tool now to enter plan mode, then:

1. **Understand the scope.** Launch one or more subagents (in the foreground — you need their results) to deeply research what this instruction touches. Find all the files, patterns, and call sites that need to change.

2. **Decompose into independent units.** Break the work into 5–30 self-contained units. Each unit must:
   - Be independently implementable in an isolated git worktree (no shared state with sibling units)
   - Be mergeable on its own without depending on another unit's PR landing first
   - Be roughly uniform in size (split large units, merge trivial ones)

   Scale the count to the actual work: few files → closer to 5; hundreds of files → closer to 30.

3. **Determine the e2e test recipe.** Figure out how a worker can verify its change actually works end-to-end — not just that unit tests pass. Look for:
   - A browser-automation tool (for UI changes)
   - A CLI-verifier pattern (for CLI changes)
   - A dev-server + curl pattern (for API changes)
   - An existing e2e/integration test suite

   If you cannot find a concrete e2e path, use the AskUserQuestion tool to ask the user.

4. **Write the plan.** In your plan file include:
   - Summary of research findings
   - Numbered list of work units (title, files/dirs, one-line description)
   - The e2e test recipe (or "skip e2e because …")
   - The exact worker instructions (shared template)

5. Call ExitPlanMode to present the plan for approval.

## Phase 2: Spawn Workers (After Plan Approval)

Once the plan is approved, spawn one background agent per work unit using the Agent tool. **All agents must use `isolation: "worktree"` and `run_in_background: true`.** Launch them all in a single message block so they run in parallel.

Each agent prompt must be fully self-contained: include the overall goal, the unit's specific task, codebase conventions discovered, the e2e test recipe, and worker instructions to:
1. **Simplify** — invoke the Skill tool with `skill_name: "simplify"`
2. **Run unit tests**
3. **Test end-to-end** per the recipe
4. **Commit and push**, create a PR with `gh pr create`
5. **Report** with a single line: `PR: <url>`

## Phase 3: Track Progress

After launching, render an initial status table:

| # | Unit | Status | PR |
|---|------|--------|----|
| 1 | <title> | running | — |

As background-agent completion notifications arrive, parse the `PR: <url>` line and re-render the table. When all done, render the final table and a one-line summary.

## Preconditions

- Must be inside a git repository (worktree spawning needs git).
- The instruction must be sweeping/mechanical (migration, refactor, bulk rename) — not a single small change.
