---
name: run
description: Run a Godot 4 game headless and get back only its errors and warnings, or check every script for parse errors. Use after editing GDScript, scenes or resources to confirm the game still loads and runs, when the user reports a bug or crash, or when asked to run, test or check the game.
---

# Run the game and read its errors

After changing GDScript, `.tscn` or `.tres` files, check your work with this script before saying it is done. It
runs Godot headless and prints only the problems, each with the file and line, merged and counted.

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/run_report.py" "<project folder>" --check
python "${CLAUDE_PLUGIN_ROOT}/scripts/run_report.py" "<project folder>"
```

- `--check` loads the whole project in the headless editor without running the game. It finds parse errors in
  every script and broken resources, also in scenes the game would not reach. Run it first after edits.
- With no flag, the game runs its main scene for 300 frames and quits. `--scene res://path.tscn` runs one scene,
  `--frames N` runs longer, and everything after `--` goes to the game (read it with `OS.get_cmdline_user_args()`).
- `--warnings-fail` treats warnings as failures.

## Reading the result

The first line says what ran, how it ended and how many problems were found. Each problem follows as
`ERROR:` or `WARNING:` with its `res://file.gd:line in function` below it. `(x5)` means the same problem repeated.

- Exit code 0: no errors. Mention any warnings that relate to your change.
- Exit code 1: errors, a crash or a timeout. Fix errors caused by your change, then run again until it is clean.
  When an error existed before your change, tell the user instead of fixing it unasked.
  A timeout means the game did not quit, which can be an infinite loop or a scene waiting for input.
- Exit code 2: setup problem (no project, Godot not found); the message says what to fix.

The full log is at `<project>/.godot/toolkit/last_run.log` (or `last_check.log`); read it only when the summary
is not enough.

A headless run has no rendering, so it cannot tell whether something looks right. Use the screenshot skill for that.

## Known noise

Add patterns for messages that are expected in this project to `toolkit.json` so they stop showing up:

```json
{"run": {"ignore": ["ObjectDB instances were leaked"]}}
```
