# Changelog

## 0.10.0 (2026-11-16)

- **brief/fred**: economic series from FRED (interest rates, inflation, jobs) with your own free key, series
  search, and FRED's required notice on every output.
- **Fixed**: `fix_deps` and `release_notes --write` kept files' content but turned Windows (CRLF) line endings
  into LF, so git showed every line as changed. Line endings are now preserved.
- Skill descriptions are shorter and name every tool their skill covers (all five packs: about 1,200 tokens per
  session in total).

## 0.9.0 (2026-11-16)

- **brief/dmi --forecast**: DMI's own HARMONIE forecast for a point, the next hours and a summary per day
  (temperature range, rain, strongest wind), next to the station measurements. Converts the model's Kelvin and
  accumulated rain, and skips hours that are already past.

## 0.8.0 (2026-11-16)

- **brief/dmi**: what the nearest DMI station measured in the last hour (temperature, humidity, wind and gusts,
  rain, pressure, visibility, cloud cover), no key needed. Prefers a full station with wind and rain when one is
  close, and says so when a place is outside Denmark. An optional `observed` section for the brief.

## 0.7.0 (2026-11-16)

- **deps/fix_deps**: also fixes projects that use a lockfile with a manifest: raises the lower bound in
  `pyproject.toml` (PEP 508 strings and Poetry tables, upper bounds respected) and sets the requirement in
  `Cargo.toml`, then prints the command that regenerates `uv.lock`, `poetry.lock`, `Cargo.lock` or the npm
  lockfile.

## 0.6.0 (2026-11-16)

- **core/release**: drafts the changelog from the commits since the last tag (conventional commits or plain
  subjects), suggests the next semver version, and with `--write` adds it to `CHANGELOG.md`. This entry was
  drafted with it.
- **core/docs-check**: the "exists with different letter case" hint now also works on case-sensitive file
  systems (Linux CI), naming the file's real spelling.

## 0.5.0 (2026-11-16)

- **core/docs-check**: broken relative links (with exact letter case), missing anchors (GitHub slugs), script
  paths in code blocks that no longer exist, and dead web links with `--external`. Checks only files git tracks.
- **deps/fix_deps**: plans the upgrades that fix known vulnerabilities, applies them to `requirements*.txt` and
  `package.json` with `--apply`, prints the command for everything else, and holds back major upgrades while
  naming the best fix on the current major line.
- **audit/plugin_scan**: static risk scan of installed plugins or a folder before installing it.
- **audit/context_cost --measure-mcp**: starts stdio MCP servers and counts their tool definitions; MCP servers
  from `.mcp.json` and the user config are listed too.
- **brief/dk_stats**: Statistics Denmark (no key): inflation, CPI and population shortcuts, table search, any
  table; an optional `inflation` section in the brief.

## 0.4.0 (2026-11-16)

Three new packs, chosen from research into the Claude Code plugin landscape and free data APIs.

- **deps**: `dep_audit` (known vulnerabilities from OSV.dev with CVSS 3.x scores, aliases merged, upgrade target
  per package), `outdated`, `licenses`, for PyPI, npm, crates.io, Go, Packagist and RubyGems; a hook that reports
  vulnerabilities an edit to a dependency file introduced.
- **brief**: morning brief, weather (Open-Meteo), Hacker News / RSS / GitHub releases, Danish holidays and working
  days, and markets: exchange rates (ECB, fallback Frankfurter), crypto (CoinGecko, fallback Kraken), stocks with
  your own free Finnhub or Tiingo key or the opt-in unofficial Yahoo source, and portfolio valuation from a CSV.
  Descriptive only, with source, time and disclaimer on every figure.
- **audit**: context cost of installed skills, agents and CLAUDE.md files; skill usage from local session logs;
  a hook doctor for missing programs, the Windows `python3` Store placeholder, CRLF scripts and bad matchers.
- `shared/netlib.py`: one standard-library HTTP layer (cache with ETag revalidation, retries honouring
  Retry-After, identifying User-Agent, keys from environment or config), synced into the packs that use it.
- CI also runs the tests on Windows.

## 0.3.0 (2026-11-16)

- `export`: every zip gets a `.sha256` checksum file. `--tag` commits the version change and creates the git
  tag `v<version>` after a successful export; it refuses on uncommitted changes or an existing tag and never
  pushes.
- `doctor`: new checks `duplicate-class` (two scripts with the same `class_name`) and `orphan-file` (`.import`
  or `.uid` files whose source is gone).
- `screenshot --steps`: `click:Container[N]` clicks the N-th visible button inside a container, for icon grids
  and other buttons without text.

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
