---
name: review-diff
description: Review a code diff for bugs / style / tests / security.
parameters:
  type: object
  properties:
    diff:
      type: string
      description: The unified diff text to review.
  required:
    - diff
---

You are reviewing a code diff. For each change:

1. **Bugs / logic errors** — flag explicitly.
2. **Style** — only mention if non-trivial.
3. **Tests** — note missing test coverage.
4. **Security** — flag sensitive patterns (eval, shell injection, etc).

Be concise. Group findings by severity. End with one-line verdict.
