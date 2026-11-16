# Changelog

## 0.2.0 (2026-11-16)

- `screenshot --steps`: drive the UI with real mouse and key events (`click`, `hover`, `key`, `wait`, `waitfor`,
  `shot`) to capture screens behind menus. Controls are found by their on-screen (translated) text, node name or
  path. A failed step saves the screen and lists the visible buttons.
- `run` and `screenshot`: a short run that ends while the game is still loading resources in the background no
  longer reports the half-read files as parse errors; they show as warnings with a hint to run more frames.
- `doctor`: paths inside BBCode and GDScript comments are handled correctly; a bad `toolkit.json` gives a clean
  error.
- CI: actions on Node 24, runner pinned to Ubuntu 24.04.

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
