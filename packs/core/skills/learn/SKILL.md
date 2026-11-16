---
name: learn
description: Turn a correction or preference into a permanent rule so it never has to be repeated. Use when the user corrects the same thing a second time, says "remember this", "always/never do X", "from now on", or "I told you before", or when a toolkit script failed in a way its skill did not cover.
---

# Learn: make a correction permanent

A correction typed twice should become a rule once. Do this in four steps.

## 1. State the rule

Write the rule as one or two plain sentences that would have prevented the mistake:

- Say what to do, not only what to avoid: "Use `Config.build_version()` for the version", not "don't hardcode it".
- Add the reason in a few words when it is not obvious, so the rule can be applied to cases it does not name.
- Keep it general enough to apply again, but no more general than what the user said.

## 2. Pick where it goes

| The rule is about | Put it in |
| --- | --- |
| This project: its code, layout, names, commands | `CLAUDE.md` in the project root (create it if missing) |
| How the user likes to work, in every project | `~/.claude/CLAUDE.md` |
| A repeated multi-step job in this project | a project skill: `.claude/skills/<name>/SKILL.md` |
| How a toolkit script or skill should behave | the toolkit repo (see below) |
| Something that must happen every time, with no judgment | a hook, not a rule: propose it to the user |

When unsure between project and global, choose project.

## 3. Write it

- Read the target file first. If a rule on the same subject exists, edit it instead of adding a second one, and
  remove rules the new one makes wrong.
- Put the rule under a fitting heading (create `## Rules` if there is none). One bullet per rule.
- Keep `CLAUDE.md` short: it is loaded in every session. A rule longer than three lines belongs in a skill.

For the toolkit repo: find its folder from the marketplace the plugin was installed from
(`claude plugin marketplace list`). A marketplace added from a local folder points at the repo itself; for one
added from GitHub, ask the user where their checkout is. Edit the skill's `SKILL.md` there, or add a line to
`docs/backlog.md` when the fix needs code. Edits in `~/.claude/plugins/` are overwritten on update, so never
edit the installed copy.

## 4. Confirm

Tell the user in one line what rule was written and where, so they can correct the wording. Then apply the rule
to the task at hand.
