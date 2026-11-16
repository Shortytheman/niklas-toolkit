---
name: deps
description: Check a project's dependencies - known vulnerabilities (OSV.dev), outdated packages, and licenses - for Python, npm, Rust, Go, PHP and Ruby. Use when the user asks about security, vulnerabilities, CVEs, outdated or old packages, upgrades, licenses, or before a release; and after adding or upgrading a dependency.
---

# Dependency health

Three scripts, no API keys, nothing to install. They read lockfiles and manifests under the project folder:
`requirements*.txt`, `poetry.lock`, `uv.lock`, `Pipfile.lock`, `pdm.lock`, `pyproject.toml`, `package-lock.json`,
`yarn.lock`, `pnpm-lock.yaml`, `package.json`, `Cargo.lock`, `Cargo.toml`, `go.sum`, `go.mod`, `composer.lock`,
`Gemfile.lock`.

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/dep_audit.py" "<project>"     # known vulnerabilities
python "${CLAUDE_PLUGIN_ROOT}/scripts/outdated.py" "<project>"      # newer releases (direct deps; --all for all)
python "${CLAUDE_PLUGIN_ROOT}/scripts/licenses.py" "<project>"      # license inventory
```

## Vulnerabilities: `dep_audit.py`

Lists each affected package with severity (CVSS 3.x score when the advisory has one), advisory id, CVE, the
versions that fix it, and the lowest version that fixes all of them ("upgrading to X fixes all of these").

- Exit 0: nothing found. Exit 1: vulnerabilities. Exit 2: no dependency files, or OSV.dev was unreachable.
- `--min-severity high` makes only high and critical count for the exit code; `--direct-only` skips transitive
  packages; `--json` for further processing.
- Packages without an exact version (ranges in `pyproject.toml` or `package.json` with no lockfile) are listed as
  "not checked": suggest a lockfile rather than guessing the installed version.

When fixing, plan with `fix_deps.py` first:

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/fix_deps.py" "<project>"            # dry run: what would change
python "${CLAUDE_PLUGIN_ROOT}/scripts/fix_deps.py" "<project>" --apply    # write the safe edits
```

1. It edits `requirements*.txt` pins, `package.json` specs (keeping `^`/`~`), `pyproject.toml` lower bounds and
   `Cargo.toml` requirements to the lowest version that fixes everything, prints the command that regenerates
   the lockfile, and the right command for transitive packages and other ecosystems. Show the
   user the dry run before `--apply` when the change is more than a few patch upgrades.
2. Major upgrades are not applied without `--allow-major`; the plan says which version on the current major
   line fixes how many advisories, which is often the safer first step. Read the changelog before crossing a
   major version, and ask the user.
3. After editing, regenerate the lockfile with the project's own tool (`uv lock`, `pip-compile`, `npm install`,
   `cargo update`), run the project's checks (the verify skill from the core pack, if installed), and run
   `dep_audit.py` again to confirm.
4. A finding that does not apply (code path unused, fix impossible) can be accepted in `toolkit.json`:
   `{"deps": {"ignore": ["GHSA-xxxx-xxxx-xxxx"]}}`. Only add it when the user agrees, with the reason.

Never claim a project is "secure" because the audit is clean: it only knows published advisories.

## Outdated: `outdated.py`

Shows `current -> latest` grouped as major, minor, patch. Major jumps (and minor jumps of 0.x packages) can
break things: upgrade those one at a time with the changelog in hand. Outdated is information, not a failure.

## Licenses: `licenses.py`

Groups packages as permissive, weak copyleft (LGPL, MPL...), copyleft (GPL, AGPL...) and unknown.
`--fail-on copyleft` makes it usable in CI. It shows what package authors declared, which can be wrong: present it
as an inventory, never as legal advice, and point the user to the package's own license file for decisions.

## The hook

After Claude edits a dependency file, the pack's hook audits it against the version in git HEAD and reports only
vulnerabilities the edit introduced. If it reports one, choose another version or explain to the user why this
one is needed.
