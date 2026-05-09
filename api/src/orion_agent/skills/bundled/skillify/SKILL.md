---
name: skillify
description: Capture this session's repeatable process into a reusable skill (writes a new SKILL.md under ~/.orion/users/<user_id>/skills/ or .orion/skills/).
---

# Skillify

You are capturing this session's repeatable process as a reusable skill that future invocations can reuse.

## Your Task

### Step 1: Analyze the Session

Before asking any questions, analyze the current session to identify:

- What repeatable process was performed
- What the inputs/parameters were
- The distinct steps (in order)
- The success artifacts/criteria for each step (e.g. not just "writing code," but "an open PR with CI fully passing")
- Where the user corrected or steered you
- What tools and permissions were needed
- What sub-agents (if any) were used
- What the goals and success artifacts were

### Step 2: Interview the User

Use AskUserQuestion (or plain text questions if AskUserQuestion isn't available) to confirm details. Iterate as much as needed.

**Round 1: High level confirmation**

- Suggest a `name` (kebab-case) and one-line `description` for the skill based on your analysis. Ask the user to confirm or rename.
- Suggest high-level goal(s) and specific success criteria for the skill.

**Round 2: More details**

- Present the high-level steps you identified as a numbered list.
- If the skill takes arguments, suggest names based on what you observed.
- Ask where the skill should be saved:
  - **This project** (`.orion/skills/<name>/SKILL.md`) — for workflows specific to this project, committed to the repo
  - **Per-user** (`~/.orion/users/<user_id>/skills/<name>/SKILL.md`) — follows you across all projects, this account only
  - **System** (`~/.orion/skills/<name>/SKILL.md`) — admin level, all tenants on this server share

**Round 3: Breaking down each step**

For each major step, ask (only if not glaringly obvious):

- What does this step produce that later steps need? (data, artifacts, IDs)
- What proves the step succeeded?
- Should the user confirm before proceeding? (especially for irreversible actions)
- Are any steps independent and could run in parallel?
- What are the hard constraints?

**Round 4: Final**

- Confirm trigger phrases — when should this skill auto-invoke?
- Any other gotchas?

Stop interviewing once you have enough information. Don't over-ask for simple processes.

### Step 3: Write the SKILL.md

Use the Write tool to create the skill file at the location chosen in Round 2. Format:

```markdown
---
name: {{skill-name}}
description: {{one-line description, < 200 chars}}
parameters:
  type: object
  properties:
    {{arg-name}}:
      type: string
      description: {{what it is}}
  required:
    - {{arg-name}}
---

# {{Skill Title}}

{{Description of skill}}

## Inputs

- `{{arg-name}}`: {{description}}

## Goal

{{Clearly stated goal for this workflow}}

## Steps

### 1. Step Name

{{What to do in this step. Be specific and actionable. Include commands when appropriate.}}

**Success criteria**: {{REQUIRED — shows when the step is done}}

### 2. ...
```

**Per-step annotations** (optional, only when useful):

- **Success criteria** — REQUIRED on every step.
- **Artifacts** — data this step produces that later steps need (e.g., PR number, commit SHA).
- **Human checkpoint** — when to pause and ask the user (irreversible actions, judgment calls).
- **Rules** — hard constraints. User corrections during the reference session are especially useful here.

**Step structure tips:**

- Steps that can run concurrently use sub-numbers: 3a, 3b
- Keep simple skills simple — a 2-step skill doesn't need annotations on every step

### Step 4: Confirm and Save

Before writing, output the complete SKILL.md content as a code block in your response so the user can review it. Then ask "Does this SKILL.md look good to save?". Only call Write after the user confirms.

After writing, tell the user:

- Where the skill was saved
- How to invoke it: via the Skill tool with `skill_name: "{{name}}"` (or pass through the Skill tool's `args` field)
- That they can edit the SKILL.md directly to refine it
