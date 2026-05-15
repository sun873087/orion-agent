---
name: stuck
description: Investigate frozen / stuck / slow agent sessions on this machine and report a diagnosis.
---

# /stuck — diagnose frozen/slow agent sessions

The user thinks another agent session on this machine is frozen, stuck, or very slow. Investigate and report back.

## What to look for

Scan for other Python / orion / claude processes (excluding the current one — for shell commands just exclude the PID running this prompt). Process names are typically `python`, `orion`, `claude`, `cli`, `uvicorn`.

Signs of a stuck session:
- **High CPU (≥90%) sustained** — likely an infinite loop. Sample twice, 1-2s apart, to confirm it's not a transient spike.
- **Process state `D` (uninterruptible sleep)** — often an I/O hang. The `state` column in `ps` output; first character matters.
- **Process state `T` (stopped)** — user probably hit Ctrl+Z by accident.
- **Process state `Z` (zombie)** — parent isn't reaping.
- **Very high RSS (≥4GB)** — possible memory leak making the session sluggish.
- **Stuck child process** — a hung `git`, `node`, or shell subprocess can freeze the parent. Check `pgrep -lP <pid>` for each session.

## Investigation steps

1. **List all candidate processes** (macOS/Linux):
   ```
   ps -axo pid=,pcpu=,rss=,etime=,state=,comm=,command= | grep -E '(orion|claude|uvicorn)' | grep -v grep
   ```

2. **For anything suspicious**, gather more context:
   - Child processes: `pgrep -lP <pid>`
   - If high CPU: sample again after 1-2s to confirm it's sustained
   - If a child looks hung (e.g., a git command), note its full command line with `ps -p <child_pid> -o command=`

3. **Consider a stack dump** for a truly frozen process (advanced, optional):
   - macOS: `sample <pid> 3` gives a 3-second native stack sample
   - Linux: `py-spy dump --pid <pid>` for Python processes

## Report

Format the findings concisely:
- PID, CPU%, RSS, state, uptime, command line, child processes
- Diagnosis of what's likely wrong
- Recommended next step (kill / wait / debug)

## Notes

- Don't kill or signal any processes — this is diagnostic only.
- If the user gave an argument (e.g., a specific PID or symptom), focus there first.
