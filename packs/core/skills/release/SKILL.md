---
name: release
description: Prepare a release - draft the changelog from commits since the last tag, pick the next semver version, bump version fields, and tag. Use when the user asks to release, cut or publish a version, write a changelog or release notes, or decide the next version number.
---

# Prepare a release

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/release_notes.py" "<project>"            # draft + suggested version
python "${CLAUDE_PLUGIN_ROOT}/scripts/release_notes.py" "<project>" --write    # add it to CHANGELOG.md
```

The draft groups commits since the last tag into Breaking, Added, Fixed, Changed, Docs and Other (conventional
commit prefixes when the project uses them, otherwise the first word), and suggests the next version: breaking
-> major (minor while 0.x), added -> minor, otherwise patch.

## Steps

1. **Check first.** Run the project's checks (the verify skill) and the docs check. Do not release with failing
   checks.
2. **Draft.** Run `release_notes.py`. Rewrite the entries for users: what changed for them, not how it was coded;
   merge related commits; drop internal noise (CI, refactors) unless it matters to users. Keep the commit hashes
   out of user-facing notes if the project's changelog does not use them.
3. **Version.** Use the suggestion unless the user says otherwise. Update every place the project stores it
   (`package.json`, `pyproject.toml`, `Cargo.toml`, plugin manifests, `project.godot` via the godot export skill's
   `--set-version`), and make them agree.
4. **Commit** the changelog and version bump together as one commit.
5. **Ask before anything outward-facing**: creating the tag, pushing, and publishing a GitHub release are
   separate steps the user approves (`git tag -a vX.Y.Z -m "..."`, `git push origin main vX.Y.Z`,
   `gh release create vX.Y.Z --notes-file ...`). Follow the project's conventions for commit messages and any
   rules the user has set about them.
