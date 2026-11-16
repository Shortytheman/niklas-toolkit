---
name: verify
description: Run the project's build, lint and test checks in one command before saying work is done. Use after finishing a code change, before committing, or when the user asks whether everything still works.
---

# Verify before saying "done"

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/verify.py" "<project folder>"
```

It runs the checks in `toolkit.json` (`"verify": [{"name": ..., "run": ...}]`), or detects them from
`package.json`, pytest, Cargo, Go or a Makefile. It prints `PASS` or `FAIL` per check and the output of failed
ones only. `--list` shows what would run.

- Exit 0: report that the checks passed, and which ones.
- Exit 1: read the failure output. Fix failures your change caused and run again. If a check already failed before
  your change, say so instead of fixing it unasked.
- Exit 2: no checks were found. Look for the project's real commands (README, CI workflow, package scripts),
  run them, and offer to write them into `toolkit.json` so the next run finds them.

Never report work as done while a check fails, and never weaken or skip a check to make it pass.

## Godot projects

In a project with `project.godot`, also use the godot pack: the doctor skill for broken references, and the run
skill (`--check`, then a short run). Those can also go into `toolkit.json` with the full script paths, so one
command covers everything.

## Long checks

When a check takes minutes, run verify in the background and tell the user it is running. Use `--only <name>`
to rerun just the check you are fixing, then run everything once at the end.
