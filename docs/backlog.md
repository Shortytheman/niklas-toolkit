# Backlog

Ideas and fixes waiting for real use to justify them. The `learn` skill adds lines here when a fix needs code.

- Godot test runner (GUT or gdUnit4): build when a project adopts one of them.
- Demo recording for the README.
- `brief`: DMI (Danish weather service) as an alternative source; check its forecast endpoints after the
  November 2026 change first.
- `brief`: FRED economic series (needs a free key and its "not endorsed" notice).
- `deps`: a `--fix` mode that writes the upgrade targets into requirements files; `docs-check` for broken links
  and README commands that no longer match the project.
- `audit`: measure MCP tool definitions by starting the servers (opt-in); a static scan of installed plugins for
  risky patterns.
- Research notes behind 0.4.0 are kept locally in `research_notes/` and `reports/` (not in the repo).

## Done

- `deps`, `brief` and `audit` packs, shared HTTP layer, Windows CI (0.4.0)
- `export` checksums and `--tag`, doctor `duplicate-class` and `orphan-file`, `screenshot` `Container[N]` (0.3.0)
- `screenshot --steps`: click, hover, keys and waits to reach screens behind menus (0.2.0)
- Project doctor, scene rules, `verify`, `handoff`, `reviewer`, pack icons (0.1.0)
