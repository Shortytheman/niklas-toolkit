# Changelog

## 0.1.0 (2026-11-15)

First release.

### godot pack

- `export`: headless export of every preset, version bump in `project.godot`, zipped builds with extra files.
- `run`: headless run or whole-project check, reporting only errors and warnings with file and line.
- `screenshot`: renders chosen frames of a scene to PNG.
- `doctor`: broken `res://` paths, letter-case mismatches that break exports, stale and unknown uids, unused files.
- `scene-rules`: rules for editing `.tscn` and `.tres` files by hand.
- GDScript lint hook: reports only the problems an edit introduced.
- `godot-index` MCP server: scene trees, resource usages, symbol definitions, unused files.
- Game runs from the tools use a sandboxed user data folder.

### core pack

- `verify`: one command for a project's checks.
- `learn`, `handoff` skills and the `reviewer` agent.
