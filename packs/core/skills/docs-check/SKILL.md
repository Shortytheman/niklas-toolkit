---
name: docs-check
description: Check a project's Markdown docs for broken relative links, missing #anchors, script paths in code blocks that no longer exist, and (optionally) dead web links. Use after renaming, moving or deleting files, after editing a README or docs, before a release, or when the user asks whether the docs are up to date.
---

# Check the docs

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/docs_check.py" "<project>"              # local links, anchors, script paths
python "${CLAUDE_PLUGIN_ROOT}/scripts/docs_check.py" "<project>" --external   # also web links (network)
```

In a git repository it checks the Markdown files git tracks or would track, so ignored folders are skipped.

| Finding | Meaning | Fix |
| --- | --- | --- |
| `missing-file` | a relative link points at nothing; "different letter case" means it works on Windows but breaks on GitHub and Linux | correct the path; find moved files with `git log --diff-filter=R --summary` |
| `missing-anchor` | `#section` matches no heading (GitHub's slugs: lowercase, punctuation dropped, spaces to `-`) | point to the heading's real slug, or rename the heading back |
| `missing-script` | a code block runs a script path that does not exist | update the command to the script's current path; if the script was removed, remove or replace the instructions |
| `dead-url` | a web link answers 404/410 or its host does not resolve | find the new address or remove the link; do not invent a replacement URL |

Links reported as "could not verify" (403, 429, timeouts, certificate errors) may well work in a browser: mention
them, but do not change them on that basis alone.

Exit 0 means clean, 1 problems found, 2 nothing to check. After moving or renaming files, run this together with the
project's other checks.
