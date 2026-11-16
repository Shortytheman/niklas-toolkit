# niklas-toolkit

A Claude Code plugin marketplace that makes Claude better at real project work: a general `core` pack used in
every project, plus one pack per domain, starting with Godot 4.

Three rules shape it:

- **Scripts do the work.** Every tool is a plain Python script (standard library only) that runs from a terminal
  or CI without Claude.
- **Skills say when and how.** A short `SKILL.md` tells Claude which script to run, with which arguments, and what
  to do when it fails.
- **Built from real pain.** A tool goes in after the same job was done by hand twice.

## Install

```bash
claude plugin marketplace add <owner>/<repo>
```

```text
/plugin install godot@niklas-toolkit
/plugin install core@niklas-toolkit
```

To try a pack from a local checkout without installing: `claude --plugin-dir ./packs/godot`.

## Packs

### `godot`: Godot 4

| Tool | Kind | What it does |
| --- | --- | --- |
| `export` | script + skill | Exports every preset headless, optionally bumps `config/version`, zips each build with extra files |
| `run` | script + skill | Runs the game headless (or loads the whole project with `--check`) and returns only errors and warnings, with `res://file.gd:line`, merged and counted |
| `screenshot` | script + skill | Runs a scene with rendering and saves chosen frames as PNG, so Claude can look at its own visual work |
| GDScript lint | hook | After every edit to a `.gd` file, reports the lint problems and syntax errors that edit introduced, compared with git HEAD |

| `godot-index` | MCP server | Answers structural questions grep handles badly: a scene's node tree, every use of a resource (by `res://` path or `uid://`), where a symbol is defined, and which files nothing references |

`godot-index` is written against the MCP protocol directly in standard-library Python (JSON-RPC over stdio), so
it starts with the pack and needs no SDK or install step. Its tools are read-only.

Game runs from `run` and `screenshot` use their own user data folder (`.godot/toolkit/userdata`), so test runs
never read or overwrite your real save files.

### `core`: every project

| Tool | Kind | What it does |
| --- | --- | --- |
| `learn` | skill | Turns a repeated correction into a permanent rule in the right place (project `CLAUDE.md`, global, a skill, or this toolkit) |

## Scripts without Claude

```bash
python packs/godot/scripts/export.py <project> --bump patch
python packs/godot/scripts/run_report.py <project> --check
python packs/godot/scripts/run_report.py <project> --frames 600 -- --some-game-arg
python packs/godot/scripts/screenshot.py <project> --scene res://ui/menu.tscn --frames 30,120
python packs/godot/servers/godot_index/godot_index.py <project> usages res://art/icon.png
```

Exit codes are the same everywhere: `0` ok, `1` the project has problems, `2` setup problem (no Godot, no project).

## Per-project settings: `toolkit.json`

Optional, in the Godot project root:

```json
{
  "godot": "C:/Tools/Godot",
  "export": {"presets": ["windows"], "include": ["docs/HOW TO PLAY.txt"]},
  "run": {"ignore": ["ObjectDB instances were leaked"]},
  "gdscript": {"format": false, "lint": true, "disable": ["max-line-length"]}
}
```

| Key | Meaning |
| --- | --- |
| `godot` | Godot executable or the folder it came in. Also `--godot` or the `GODOT_BIN` environment variable. |
| `export.presets` | Presets to export by default (otherwise all) |
| `export.include` | Files added to every zip, relative to the project |
| `run.ignore` | Regular expressions for expected messages to leave out of reports |
| `gdscript.format` | Run `gdformat` after each edit. Only for code that is already gdformat-clean. |
| `gdscript.disable` | gdlint rules the hook should not report |

The lint hook needs gdtoolkit: `python -m pip install "gdtoolkit==4.*"`.

## Results

Measured on YouTD - The Roguelike, a Godot 4.7 tower defense game with 750 GDScript files:

| Job | Before | With the toolkit |
| --- | --- | --- |
| Release export + zip | manual: editor, export dialog, copy, zip | one command, about 1.5 min, no interaction |
| Check every script for parse errors | open the editor | `run_report.py --check`, 30 s |
| Look at a UI change | run the game and look | `screenshot.py`, 25 s, Claude reads the PNG |

## Development

```bash
python -m pip install pytest "gdtoolkit==4.*"
GODOT_BIN=/path/to/godot python -m pytest tests
claude plugin validate --strict ./packs/godot
```

Tests that start Godot are skipped when no Godot is found. CI runs everything on Linux with a headless Godot
4.7.2 and validates every manifest with `--strict`.

```text
.claude-plugin/marketplace.json   lists the packs
packs/<pack>/                     one plugin per pack: skills/, hooks/, scripts/, servers/, .mcp.json
tests/                            pytest suite and fixture Godot projects
docs/plan.md                      roadmap
```

## License

MIT
