---
name: doctor
description: Find broken resource references in a Godot 4 project without running it - missing files, wrong letter case that breaks exports, stale uids, and unused assets. Use before an export or release, after moving, renaming or deleting files, when the game fails to load a resource, or when the user asks to clean up the project.
---

# Project doctor

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/doctor.py" "<project folder>"
python "${CLAUDE_PLUGIN_ROOT}/scripts/doctor.py" "<project folder>" --unused
```

It reads every scene, resource, script and data file (no Godot needed, a few seconds) and reports by check:

| Check | Meaning | What to do |
| --- | --- | --- |
| `broken-path` | a `res://` path points at nothing | find where the file went (`git log --diff-filter=DR -- <path>`) and fix the path, or remove dead references |
| `wrong-case` | the path's letter case differs from the file | fix the path to match the file exactly; Windows hides this, exports break on it |
| `stale-uid` | an `ext_resource` uid names a different file than its path | Godot loads the uid's file; check which one is meant, then fix the path or remove the `uid="..."` so Godot regenerates it |
| `unknown-uid` | a `uid://` nobody owns | replace it with the `res://` path |
| `unused` | nothing references the file (`--unused` only) | candidates only, never delete without asking |

Exit code 1 means errors were found, 0 none, 2 setup problem.

## Rules

- Fix only what the user asked for. When the doctor runs as part of other work, report its findings and ask
  before fixing ones that are not related to the task.
- Before deleting an "unused" file, check it with the `godot_find_usages` tool (when the godot-index server is
  available) and `grep` for its file name: code can build paths at runtime, which no static check can see.
- After fixing paths, run the `run` skill with `--check` to confirm the project still loads.
- Known findings that are intentional go into `toolkit.json` so they stop showing:
  `{"doctor": {"ignore": ["res://assets/sfx/"]}}` (regular expressions matched against the file and message).
