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

When fixing:

1. Upgrade direct dependencies to the version the audit names, in the manifest and the lockfile, using the
   project's own tool (`pip install -U`, `npm install x@ver`, `cargo update -p`, `uv lock --upgrade-package`).
2. For a transitive package, upgrade the direct dependency that pulls it in, or use the ecosystem's override
   mechanism (`overrides` in package.json, a constraint in requirements) and say so.
3. Check major jumps with `outdated.py` and the changelog before applying them, then run the project's checks
   (the verify skill from the core pack, if installed) and the audit again.
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
