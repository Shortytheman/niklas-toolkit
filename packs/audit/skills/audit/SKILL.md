---
name: audit
description: Audit the user's Claude Code setup - context tokens used by installed skills, agents, commands and CLAUDE.md files, skills that never get used, and hooks that fail (missing programs, Windows python3 Store stub, CRLF scripts). Use when the user asks why context fills up, what their plugins cost, which skills they use, to clean up their setup, or why a hook does not work.
---

# Audit the Claude Code setup

Local and read-only: these scripts read `~/.claude` and the project's `.claude` folder, change nothing and send
nothing anywhere.

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/context_cost.py" "<project>"   # tokens per plugin, largest items
python "${CLAUDE_PLUGIN_ROOT}/scripts/skill_usage.py" "<project>" --days 30   # used vs never used
python "${CLAUDE_PLUGIN_ROOT}/scripts/hook_doctor.py" "<project>"    # hooks that will fail, and why
python "${CLAUDE_PLUGIN_ROOT}/scripts/plugin_scan.py" "<project>"    # risky patterns in installed plugins
python "${CLAUDE_PLUGIN_ROOT}/scripts/plugin_scan.py" --path <dir>   # a plugin before installing it
```

`context_cost.py --measure-mcp` also starts each configured stdio MCP server and counts the tokens of its tool
definitions. That runs the servers' programs: ask the user first, unless they asked for the measurement.

## Reading the results

- **context_cost**: "always" is what loads into every session (names and descriptions of skills, agents and
  commands, and every applicable CLAUDE.md in full); "on use" is what a skill adds when it runs. MCP servers are
  listed but not measured: their tool definitions load at start too. Numbers are estimates (~4 characters per
  token).
- **skill_usage** counts Skill calls, subagent launches and slash commands in the local session logs. It reads
  names only. A skill that is rarely used can still be worth keeping; present the list, do not judge it.
- **hook_doctor** names the hook, where it is configured, and the fix. `store-python` means `python3` opens the
  Microsoft Store: the fix is installing Python or turning off the alias (Settings > Apps > Advanced app settings
  > App execution aliases). `crlf-script` means a `.sh` file has Windows line endings.

- **plugin_scan** lists download-and-run commands, obfuscated code, access to SSH keys, credentials or browser
  data, destructive deletes, hooks that use the network, environment dumps, and skill text that steers Claude
  to hide things from the user or skip permission prompts. A finding is a reason to read the file, not proof of
  bad intent: open the file, explain what the code does, and let the user decide. Findings marked "declared
  pattern file" come from security tools that spell out the patterns they search for.

## Acting on it

Suggest changes; make them only when the user agrees, because they change how every session behaves:

- Disable plugins the user does not need in this project (`/plugin`, or `enabledPlugins` in the project's
  `.claude/settings.json`) rather than uninstalling them.
- Shorten a long CLAUDE.md by moving procedures into skills (they load only when used).
- Fix hook problems in the file the report names. For a plugin's hook, report it to the plugin's author instead
  of editing the installed copy, which is overwritten on update.
