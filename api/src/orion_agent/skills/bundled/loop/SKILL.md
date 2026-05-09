---
name: loop
description: Run a prompt or slash command on a recurring interval (e.g. /loop 5m /foo, defaults to 10m).
---

# /loop — schedule a recurring prompt

Parse the user's input into `[interval] <prompt…>` and schedule it with the CronCreate tool.

## Parsing (in priority order)

1. **Leading token**: if the first whitespace-delimited token matches `^\d+[smhd]$` (e.g. `5m`, `2h`), that's the interval; the rest is the prompt.
2. **Trailing "every" clause**: otherwise, if the input ends with `every <N><unit>` or `every <N> <unit-word>` (e.g. `every 20m`, `every 5 minutes`, `every 2 hours`), extract that as the interval and strip it from the prompt. Only match when what follows "every" is a time expression — `check every PR` has no interval.
3. **Default**: otherwise, interval is `10m` and the entire input is the prompt.

If the resulting prompt is empty, show usage `/loop [interval] <prompt>` and stop — do not call CronCreate.

Examples:
- `5m /babysit-prs` → interval `5m`, prompt `/babysit-prs` (rule 1)
- `check the deploy every 20m` → interval `20m`, prompt `check the deploy` (rule 2)
- `run tests every 5 minutes` → interval `5m`, prompt `run tests` (rule 2)
- `check the deploy` → interval `10m`, prompt `check the deploy` (rule 3)
- `check every PR` → interval `10m`, prompt `check every PR` (rule 3 — "every" not followed by time)

## Interval → cron

| Interval pattern   | Cron expression     | Notes                                   |
|--------------------|---------------------|-----------------------------------------|
| `Nm` where N ≤ 59  | `*/N * * * *`       | every N minutes                         |
| `Nm` where N ≥ 60  | `0 */H * * *`       | round to hours (H = N/60, must divide 24)|
| `Nh` where N ≤ 23  | `0 */N * * *`       | every N hours                           |
| `Nd`               | `0 0 */N * *`       | every N days at midnight local          |
| `Ns`               | treat as `ceil(N/60)m` | cron minimum granularity is 1 minute |

**If the interval doesn't cleanly divide its unit** (e.g. `7m` → `*/7 * * * *` gives uneven gaps; `90m` → 1.5h which cron can't express), pick the nearest clean interval and tell the user what you rounded to before scheduling.

## Action

1. Call CronCreate with:
   - `cron`: the expression from the table above
   - `prompt`: the parsed prompt verbatim (slash commands pass through unchanged)
2. Briefly confirm: what's scheduled, the cron expression, the human-readable cadence, and that they can cancel with CronDelete (include the job ID).
3. **Then immediately execute the parsed prompt now** — don't wait for the first cron fire.

## Usage

If the user calls this with no input, show:

```
Usage: /loop [interval] <prompt>

Run a prompt or slash command on a recurring interval.
Intervals: Ns, Nm, Nh, Nd (e.g. 5m, 30m, 2h, 1d). Minimum granularity is 1 minute.
If no interval is specified, defaults to 10m.

Examples:
  /loop 5m /babysit-prs
  /loop 30m check the deploy
  /loop 1h /standup 1
  /loop check the deploy          (defaults to 10m)
  /loop check the deploy every 20m
```
