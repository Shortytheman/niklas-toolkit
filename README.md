# niklas-toolkit

A Claude Code plugin marketplace with five packs: a general `core`, Godot 4 game development, dependency health,
everyday information and markets, and an audit of your Claude Code setup.

Three rules shape it:

- **Scripts do the work.** Every tool is a plain Python script, standard library only, that runs from a terminal
  or CI without Claude. Nothing to `pip install` (the GDScript lint hook is the one exception).
- **Skills say when and how.** A short `SKILL.md` tells Claude which script to run, with which arguments, and what
  to do when it fails.
- **Built from real pain.** A tool goes in after the same job was done by hand twice.

## Install

```bash
claude plugin marketplace add Shortytheman/niklas-toolkit
```

```text
/plugin install core@niklas-toolkit
/plugin install deps@niklas-toolkit
/plugin install brief@niklas-toolkit
/plugin install audit@niklas-toolkit
/plugin install godot@niklas-toolkit
```

Install only the packs you need: each one costs a little context in every session (the `audit` pack measures how
much). To try a pack from a local checkout: `claude --plugin-dir ./packs/deps`.

## Packs

### `core`: every project

| Tool | Kind | What it does |
| --- | --- | --- |
| `verify` | script + skill | Runs the project's checks (from `toolkit.json`, or detected: npm, pytest, cargo, go, make) with one `PASS`/`FAIL` line each |
| `learn` | skill | Turns a repeated correction into a permanent rule in the right place (project `CLAUDE.md`, global, a skill, or this toolkit) |
| `handoff` | skill | Saves the state of unfinished work to `.claude/handoff.md` and resumes from it in the next session |
| `docs-check` | script + skill | Broken relative links (letter case included), missing `#anchors`, script paths in code blocks that no longer exist, and with `--external` dead web links |
| `reviewer` | agent | Reviews a finished diff in a fresh context for bugs, missed callers and broken project rules, and confirms each finding before reporting it |

### `deps`: dependency health, any language

| Tool | Kind | What it does |
| --- | --- | --- |
| `dep_audit` | script + skill | Known vulnerabilities from OSV.dev (no key) for PyPI, npm, crates.io, Go, Packagist and RubyGems lockfiles: severity with CVSS 3.x score, CVE, fixed versions, and the lowest version that fixes them all |
| `fix_deps` | script + skill | Plans the upgrades that fix them (dry run), and with `--apply` edits `requirements*.txt` and `package.json`; prints the right command for lockfiles and other ecosystems; holds back major upgrades and names the safest fix on the current major line |
| `outdated` | script + skill | Newer releases of direct dependencies, sorted major / minor / patch |
| `licenses` | script + skill | License inventory: permissive, weak copyleft, copyleft, unknown; `--fail-on copyleft` for CI |
| dependency hook | hook | After an edit to a lockfile or requirements file, reports only the vulnerabilities that edit introduced, compared with git HEAD |

Reads `requirements*.txt`, `poetry.lock`, `uv.lock`, `Pipfile.lock`, `pdm.lock`, `pyproject.toml`,
`package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `package.json`, `Cargo.lock`, `go.sum`, `go.mod`,
`composer.lock` and `Gemfile.lock`. TOML lockfiles work on Python 3.10 too (built-in fallback reader).

### `brief`: everyday information and markets

| Tool | Kind | What it does |
| --- | --- | --- |
| `brief` | script + skill | A morning brief from your settings: weather, next holiday, currencies, crypto, stocks, portfolio, headlines, new releases. One failing source never sinks the rest |
| `weather` | script | Now and the next days, from Open-Meteo |
| `news` | script | Hacker News top stories, your RSS/Atom feeds, and new GitHub releases (via `releases.atom`, no API limit) |
| `holidays_dk` | script | Danish public holidays computed offline from Easter, and working days in a period |
| `dk_stats` | script | Statistics Denmark without a key: inflation, CPI, population shortcuts, plus search, table info and any table |
| `fx` | script + `markets` skill | Exchange rates and history from the ECB (fallback Frankfurter) |
| `crypto` | script + `markets` skill | Prices and history from CoinGecko (fallback Kraken) |
| `stocks` | script + `markets` skill | Quotes and history with your own free Finnhub or Tiingo key; Nordic tickers like `NOVO-B.CO` through an opt-in, clearly labelled unofficial Yahoo source |
| `portfolio` | script + `markets` skill | Values your holdings CSV in DKK (or another currency): value, gain/loss, weight |

**Information only, never investment advice.** The scripts print descriptive numbers (prices, changes, low/high,
largest fall from a high, volatility) with their source and time, and a disclaimer. The `markets` skill forbids
Claude from recommending, predicting or trading. Free data tiers are for personal use, so every user brings their
own keys; the toolkit never ships or shares one. Weather data: Open-Meteo.com, CC BY 4.0.

Settings live in one personal file outside any project (`python packs/brief/scripts/brief_config.py --init`
creates it): location, currency, watchlists, feeds, repos and keys.

### `audit`: your Claude Code setup

| Tool | Kind | What it does |
| --- | --- | --- |
| `context_cost` | script + skill | Tokens that skills, agents, commands and CLAUDE.md files load into every session, per plugin; `--measure-mcp` starts each stdio MCP server and counts its tool definitions too |
| `plugin_scan` | script + skill | Static risk scan of installed plugins, or a folder before you install it: download-and-run, obfuscated code, access to keys and browser data, destructive deletes, network hooks, skill text that steers Claude to hide things or skip permissions |
| `skill_usage` | script + skill | Which skills and agents your local session logs show in use, and which never fire |
| `hook_doctor` | script + skill | Hooks that will fail: missing programs, the Windows `python3` Store placeholder, missing scripts, CRLF `.sh` files, bad matchers |

Local and read-only: reads `~/.claude` and the project's `.claude`, changes nothing, sends nothing.

### `godot`: Godot 4

| Tool | Kind | What it does |
| --- | --- | --- |
| `export` | script + skill | Exports every preset headless, optionally bumps `config/version`, zips each build with extra files and a SHA-256 checksum, and with `--tag` tags the release in git |
| `run` | script + skill | Runs the game headless (or loads the whole project with `--check`) and returns only errors and warnings, with `res://file.gd:line`, merged and counted |
| `screenshot` | script + skill | Runs a scene with rendering and saves chosen frames as PNG, so Claude can look at its own visual work. `--steps "click:Settings; wait:30; shot:settings"` drives the UI with real input to reach screens behind menus |
| `doctor` | script + skill | Finds broken `res://` paths, wrong letter case (fine on Windows, broken in exports), stale and unknown uids, duplicate `class_name`s, leftover `.import`/`.uid` files, and unused files, without running Godot |
| `scene-rules` | skill | Rules for editing `.tscn` / `.tres` files as text, written for Godot 4.7 |
| GDScript lint | hook | After every edit to a `.gd` file, reports the lint problems and syntax errors that edit introduced, compared with git HEAD |
| `godot-index` | MCP server | A scene's node tree, every use of a resource (by `res://` path or `uid://`), where a symbol is defined, and which files nothing references |

`godot-index` speaks the MCP protocol directly in standard-library Python (JSON-RPC over stdio), so it starts with
the pack and needs no SDK. Game runs from `run` and `screenshot` use their own user data folder
(`.godot/toolkit/userdata`), so test runs never touch your real save files.

## Scripts without Claude

```bash
python packs/deps/scripts/dep_audit.py <project>
python packs/deps/scripts/outdated.py <project>
python packs/brief/scripts/brief.py
python packs/brief/scripts/fx.py 100 USD DKK
python packs/brief/scripts/stocks.py --history NOVO-B.CO --days 180
python packs/audit/scripts/context_cost.py <project>
python packs/godot/scripts/export.py <project> --bump patch
python packs/godot/scripts/screenshot.py <project> --steps "wait:30; click:Settings; wait:30; shot:settings"
python packs/core/scripts/verify.py <project>
```

Exit codes are the same everywhere: `0` ok, `1` the project has problems, `2` setup or network problem.

## Per-project settings: `toolkit.json`

Optional, in the project root:

```json
{
  "godot": "C:/Tools/Godot",
  "export": {"presets": ["windows"], "include": ["docs/HOW TO PLAY.txt"]},
  "run": {"ignore": ["ObjectDB instances were leaked"]},
  "gdscript": {"format": false, "lint": true, "disable": ["max-line-length"]},
  "doctor": {"ignore": ["res://assets/sfx/"]},
  "deps": {"ignore": ["GHSA-xxxx-xxxx-xxxx"]},
  "verify": [{"name": "tests", "run": "python -m pytest -q", "timeout": 900}]
}
```

| Key | Meaning |
| --- | --- |
| `godot` | Godot executable or the folder it came in. Also `--godot` or the `GODOT_BIN` environment variable. |
| `export.presets` / `export.include` | Presets to export by default, and files added to every zip |
| `run.ignore` | Regular expressions for expected messages to leave out of reports |
| `gdscript.format` / `gdscript.disable` | Run `gdformat` after each edit (only for gdformat-clean code); gdlint rules not to report |
| `doctor.ignore` | Regular expressions for known doctor findings |
| `deps.ignore` | Advisory ids (GHSA, CVE, PYSEC...) accepted after review |
| `verify` | Checks for `verify.py`: `name`, `run` (a shell command), optional `timeout` and `cwd` |

## Results

Measured on YouTD - The Roguelike, a Godot 4.7 tower defense game with 750 GDScript files:

| Job | Before | With the toolkit |
| --- | --- | --- |
| Release export + zip | manual: editor, export dialog, copy, zip | one command, about 1.5 min, no interaction |
| Check every script for parse errors | open the editor | `run_report.py --check`, 30 s |
| Look at a UI change | run the game and look | `screenshot.py`, 25 s, Claude reads the PNG |
| Find broken references in 8,280 files | not done | `doctor.py`, 6 s |

The first doctor run found a bug that only existed in release builds: the map props' data file sat in a folder
Godot excludes from exports, so every exported build shipped without map props while the editor showed them.

`dep_audit.py` checks a project's whole dependency tree in one OSV.dev request: a demo project with seven pinned
packages from 2023 and earlier showed 29 known vulnerabilities in six of them, with the version that fixes each
package, in under 3 seconds.

## Development

```bash
python -m pip install pytest "gdtoolkit==4.*"
GODOT_BIN=/path/to/godot python -m pytest tests
python tools/sync_shared.py          # after editing shared/netlib.py
claude plugin validate --strict ./packs/deps
```

The tests never touch the network: a fake transport serves recorded answers. Tests that start Godot are skipped
when no Godot is found. CI runs the suite on Linux (Python 3.10 and 3.13, with a headless Godot 4.7.2) and on
Windows, and validates every manifest with `--strict`.

```text
.claude-plugin/marketplace.json   lists the packs
packs/<pack>/                     one plugin per pack: skills/, hooks/, agents/, scripts/, servers/
shared/netlib.py                  HTTP layer (cache, retries, User-Agent, keys), copied into packs that need it
tests/                            pytest suite, fixture Godot projects, fake network
tools/                            icon drawing, shared-code sync
docs/backlog.md                   ideas waiting for real use
```

## License

MIT
