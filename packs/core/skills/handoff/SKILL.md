---
name: handoff
description: Save the current work's state to .claude/handoff.md so the next session continues without re-discovering it, or resume from that file. Use when the user says stop, pause, hand off, "continue tomorrow" or "save where we are", when a long conversation is mid-task, or when asked to continue and the file exists.
---

# Handoff: save and resume work

The next session starts with no memory of this one. A good handoff lets it start working in one minute.

## Saving

Write `.claude/handoff.md` in the project root (replace an older one; the old state is no longer true):

```markdown
# Handoff: <task in a few words>

Updated <date and time> · branch `<branch>` · last commit `<short hash> <subject>`

## Goal
What the user wants, in their terms, and what done looks like.

## Done
- What is finished and verified (say how it was verified).

## In progress
- What is half done: which file, what is left in it. Uncommitted changes and why they are not committed.

## Next steps
1. The very next action, concrete enough to start without thinking.
2. ...

## Decisions
- Choices made and why, so they are not reopened. Include what the user decided.

## Open questions
- What is unknown or waiting for the user.

## Gotchas
- Things that cost time: failing commands, misleading errors, files not to touch.
```

Get the facts, not memory: run `git status --short`, `git log --oneline -5` and `git diff --stat`. Keep it under
about 60 lines; link to files instead of pasting them. Then tell the user where the file is.

Add `.claude/handoff.md` to `.gitignore` unless the user wants it committed.

## Resuming

1. Read `.claude/handoff.md`.
2. Check it against reality: `git status`, `git log --oneline -5`. If the branch or commits differ, tell the user
   what changed since the handoff.
3. Summarize the goal and the next step to the user in two or three lines, then continue with the next step.
4. When the task is finished, delete the handoff file or tell the user it is stale.
