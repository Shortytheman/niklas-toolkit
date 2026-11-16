---
name: export
description: Export a Godot 4 game to playable builds (exe/pck zipped for release), optionally bumping the version first. Use when the user asks to export, build, package, or release the game, or to make a new version or zip of it.
---

# Export a Godot project

Run the export script instead of exporting by hand. It exports every preset headless, puts each build in
`export/builds/<preset>/`, and zips it as `export/builds/<name> <version> <preset>.zip`.

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/export.py" "<project folder>"
```

Options:

- `--bump patch|minor|major` raises `config/version` in `project.godot` before exporting. Use it only when the
  user asks for a new version. Bug fixes are `patch`, features `minor`.
- `--set-version X.Y.Z` writes an exact version instead.
- `--preset NAME` exports one preset (repeatable). `--debug` makes a debug build. `--no-zip` skips the zip.

Defaults come from `toolkit.json` in the project root, when it exists:

```json
{"godot": "C:/Tools/Godot", "export": {"presets": ["windows"], "include": ["docs/HOW TO PLAY.txt"]}}
```

An export takes minutes. Run it in the background with a long timeout (at least 10 minutes), and tell the user it
has started.

## Reading the result

The script prints one line per preset and ends with `Done in Ns: X ok, Y failed`.

- Exit code 0: report the zip path(s) and the time.
- Exit code 1: a preset failed. The lines under `FAILED` are the errors from Godot's log, and the full log is at
  `export/builds/<preset>/export.log`. Read the errors, fix the cause in the project if it is a script or
  resource error, and run the export again. Do not edit `export_presets.cfg` unless the user asks.
- Exit code 2: setup problem, and the message says which:
  - Godot not found: ask the user for the path and add `"godot": "<path>"` to `toolkit.json`.
  - Export template missing: tell the user to install it in the editor (Editor > Manage Export Templates).
    Do not download templates yourself.
  - Unknown preset: the message lists the presets that exist.

## After a version bump

`config/version` is the game's version. If the project has patch notes or a changelog, remind the user to add an
entry for the new version, or write it if they described the changes.
