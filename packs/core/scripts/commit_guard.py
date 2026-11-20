#!/usr/bin/env python3
"""Stop a `git commit` or `git push` that would publish a secret or a commit message the user has forbidden.

Claude Code PreToolUse hook for Bash. Standard library only (calls git). It looks at the command before it runs:

- git commit: the changes being committed (staged ones; with `git add` earlier in the same command or `-a`, every
  change against HEAD and new untracked files too) and the message given with -m/--message/-F.
- git push: the commits and tags the push would publish (everything not yet on a remote): their messages and
  the lines they add.

Secrets: private keys, AWS, GitHub, GitLab, Slack, Stripe, Google, OpenAI and Anthropic keys, and files that
usually hold them (.env, id_rsa, *.pem, *.p12...). Values are shown masked. A line containing
"commit-guard: allow" is skipped, so a test fixture can opt out.

Forbidden message patterns are regular expressions from "commit_guard": {"forbid": [...]} in the project's
toolkit.json and in the toolkit's user config (<toolkit folder>/config.json), so a rule such as "no AI
attribution lines" can hold in every repository. "allow_paths" (globs) skips files such as test fixtures.

Exit codes follow the hook protocol: 0 let the command run (also when the check itself fails: the guard never
blocks work because of its own error), 2 block it and tell Claude why on stderr.
Set TOOLKIT_COMMIT_GUARD=off to disable it for one session.

By hand:  python commit_guard.py --commit [repo]    check what is staged now
          python commit_guard.py --push [repo]      check what a push would publish
"""
from __future__ import annotations

import fnmatch
import json
import os
import platform
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ALLOW_MARK = "commit-guard: allow"
MAX_SCAN_BYTES = 8_000_000
SECRETS = [
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY( BLOCK)?-----")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b")),
    ("GitLab token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b")),
    ("Slack token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}\b")),
    ("Stripe live key", re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{20,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("OpenAI API key", re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{40,}")),
]
SECRET_FILES = ["*.pem", "*.key", "*.p12", "*.pfx", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", ".env",
                ".env.*", "*.keystore", "credentials.json", "service-account*.json"]
SAFE_FILES = [".env.example", ".env.sample", ".env.template", ".env.dist", "*.pub"]


@dataclass
class Finding:
    kind: str       # secret | file | message
    where: str
    detail: str


# --- configuration ------------------------------------------------------------------------------------------------

def user_config_path() -> Path:
    if os.environ.get("TOOLKIT_HOME"):
        return Path(os.environ["TOOLKIT_HOME"]) / "config.json"
    if platform.system() == "Windows" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "niklas-toolkit" / "config.json"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "niklas-toolkit" / "config.json"


def load_rules(repo: Path) -> tuple[list[tuple[re.Pattern, str]], list[str]]:
    """(forbidden message patterns with their source, allowed path globs) from user and project config."""
    forbid, allow = [], []
    for label, path in (("user config", user_config_path()), ("toolkit.json", repo / "toolkit.json")):
        try:
            cfg = json.loads(path.read_text(encoding="utf-8")).get("commit_guard") or {}
        except (OSError, ValueError, AttributeError):
            continue
        for pattern in cfg.get("forbid", []):
            try:
                forbid.append((re.compile(pattern), f"{pattern!r} from {label}"))
            except re.error:
                pass
        allow += cfg.get("allow_paths", [])
    return forbid, allow


# --- reading the command ------------------------------------------------------------------------------------------

def segments(command: str) -> list[list[str]]:
    """The command split into simple commands (at && || ; | and newlines), each as argv. Falls back to one raw
    segment when the shell syntax is beyond shlex (heredocs, unbalanced quotes)."""
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=";&|\n")
        lex.whitespace = " \t\r"            # a newline separates commands, like ; does
        lex.whitespace_split = True
        lex.commenters = ""
        out, cur = [], []
        for tok in lex:
            if tok and set(tok) <= set(";&|\n"):
                out.append(cur)
                cur = []
            else:
                cur.append(tok)
        out.append(cur)
        return [a for a in out if a]
    except ValueError:
        return [command.split()]


def git_action(argv: list[str]) -> tuple[str, list[str], str | None] | None:
    """('commit'|'push'|'add', the arguments after it, the -C directory) for a git command, else None."""
    if not argv or Path(argv[0]).name.lower() not in ("git", "git.exe"):
        return None
    i, cdir = 1, None
    while i < len(argv) and argv[i].startswith("-"):
        if argv[i] in ("-C", "-c", "--git-dir", "--work-tree") and i + 1 < len(argv):
            if argv[i] == "-C":
                cdir = argv[i + 1]
            i += 2
        else:
            i += 1
    if i < len(argv) and argv[i] in ("commit", "push", "add"):
        return argv[i], argv[i + 1:], cdir
    return None


def commit_messages(args: list[str], cwd: Path) -> list[str]:
    msgs, i = [], 0
    while i < len(args):
        a = args[i]
        if a in ("-m", "--message") and i + 1 < len(args):
            msgs.append(args[i + 1])
            i += 2
            continue
        if a.startswith("--message="):
            msgs.append(a.split("=", 1)[1])
        elif a.startswith("-m") and len(a) > 2 and not a.startswith("--"):
            msgs.append(a[2:])
        elif a in ("-F", "--file") and i + 1 < len(args):
            try:
                msgs.append((cwd / args[i + 1]).read_text(encoding="utf-8", errors="replace"))
            except OSError:
                pass
            i += 2
            continue
        elif a.startswith("-") and not a.startswith("--") and "a" in a[1:] and "m" in a[1:] and i + 1 < len(args):
            msgs.append(args[i + 1])        # -am "msg"
            i += 2
            continue
        i += 1
    return msgs


# --- git ----------------------------------------------------------------------------------------------------------

def git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "replace").strip())
    return r.stdout[:MAX_SCAN_BYTES].decode("utf-8", "replace")


def added_lines(diff: str) -> list[tuple[str, int, str]]:
    """(file, line number, text) for every added line in a unified diff."""
    out, file, line = [], "", 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            file = raw[6:] if raw.startswith("+++ b/") else raw[4:]
        elif raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            line = int(m.group(1)) if m else 0
        elif raw.startswith("+") and not raw.startswith("+++"):
            out.append((file, line, raw[1:]))
            line += 1
        elif not raw.startswith("-"):
            line += 1 if raw.startswith(" ") else 0
    return out


def mask(value: str) -> str:
    return value[:6] + "..." + f"({len(value)} chars)"


def scan_lines(lines: list[tuple[str, int, str]], allow: list[str]) -> list[Finding]:
    found = []
    for file, n, text in lines:
        if ALLOW_MARK in text or any(fnmatch.fnmatch(file, g) for g in allow):
            continue
        for label, rx in SECRETS:
            m = rx.search(text)
            if m:
                found.append(Finding("secret", f"{file}:{n}", f"{label} {mask(m.group(0))}"))
                break
    return found


def scan_files(names: list[str], allow: list[str]) -> list[Finding]:
    found = []
    for name in names:
        base = name.rsplit("/", 1)[-1]
        if any(fnmatch.fnmatch(name, g) for g in allow) or any(fnmatch.fnmatch(base, g) for g in SAFE_FILES):
            continue
        if any(fnmatch.fnmatch(base, g) for g in SECRET_FILES):
            found.append(Finding("file", name, "a file that usually holds secrets is being committed"))
    return found


def check_commit(repo: Path, args: list[str], adds_first: bool, forbid, allow) -> list[Finding]:
    everything = adds_first or any(a in ("-a", "--all") or (re.fullmatch(r"-[a-zA-Z]*a[a-zA-Z]*", a) and
                                                             not a.startswith("--")) for a in args)
    has_head = subprocess.run(["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=repo,
                              capture_output=True).returncode == 0
    base = ["HEAD"] if has_head else []
    if everything and has_head:
        diff = git(repo, "diff", *base, "-U0", "--no-color", "--no-ext-diff")
        names = git(repo, "diff", *base, "--name-only", "--diff-filter=A").splitlines()
    else:
        diff = git(repo, "diff", "--cached", "-U0", "--no-color", "--no-ext-diff")
        names = git(repo, "diff", "--cached", "--name-only", "--diff-filter=A").splitlines()
    lines = added_lines(diff)
    if adds_first:                          # `git add -A && git commit`: new files are not staged yet
        for name in git(repo, "ls-files", "--others", "--exclude-standard").splitlines():
            names.append(name)
            path = repo / name
            try:
                if path.stat().st_size <= 1_000_000:
                    data = path.read_bytes()
                    if b"\0" not in data[:4096]:
                        lines += [(name, i + 1, t) for i, t in
                                  enumerate(data.decode("utf-8", "replace").splitlines())]
            except OSError:
                pass
    found = scan_lines(lines, allow) + scan_files(names, allow)
    for msg in commit_messages(args, repo):
        found += check_message(msg, "commit message", forbid)
    return found


def check_message(text: str, where: str, forbid) -> list[Finding]:
    out = []
    for rx, source in forbid:
        m = rx.search(text)
        if m:
            out.append(Finding("message", where, f"contains {m.group(0)!r}, forbidden by {source}"))
    return out


def push_refs(repo: Path, args: list[str]) -> list[str]:
    if any(a in ("--all", "--mirror", "--tags") for a in args):
        return ["--all"]
    refs = ["HEAD"]
    for a in args:
        if a.startswith("-"):
            continue
        name = a.split(":", 1)[0].lstrip("+")
        if name and subprocess.run(["git", "rev-parse", "--verify", "-q", f"{name}^{{commit}}"], cwd=repo,
                                   capture_output=True).returncode == 0:
            refs.append(name)
    return refs


def check_push(repo: Path, args: list[str], forbid, allow) -> list[Finding]:
    refs = push_refs(repo, args)
    found = []
    log = git(repo, "log", *refs, "--not", "--remotes", "--format=%x1e%h%x1f%B")
    for rec in log.split("\x1e"):
        if "\x1f" in rec:
            short, body = rec.split("\x1f", 1)
            found += check_message(body, f"commit {short}", forbid)
    for a in args:                          # annotated tag messages
        name = a.split(":", 1)[0].lstrip("+")
        if name and not name.startswith("-"):
            try:
                body = git(repo, "tag", "-l", "--format=%(contents)", name)
            except RuntimeError:
                continue
            if body.strip():
                found += check_message(body, f"tag {name}", forbid)
    patch = git(repo, "log", *refs, "--not", "--remotes", "-p", "-U0", "--no-color", "--no-ext-diff",
                "--format=")
    found += scan_lines(added_lines(patch), allow)
    added = git(repo, "log", *refs, "--not", "--remotes", "--name-only", "--diff-filter=A", "--format=")
    found += scan_files(sorted({n for n in added.splitlines() if n}), allow)
    return found


# --- entry points -------------------------------------------------------------------------------------------------

def check_command(command: str, cwd: Path) -> tuple[str, list[Finding]] | None:
    """('commit'|'push', findings) for the first git commit/push in a shell command, or None."""
    added = False
    for argv in segments(command):
        if argv and argv[0] == "cd" and len(argv) > 1:
            cwd = (cwd / argv[1]).resolve()
            continue
        action = git_action(argv)
        if not action:
            continue
        verb, args, cdir = action
        repo = (cwd / cdir).resolve() if cdir else cwd
        if verb == "add":
            added = True
            continue
        try:
            top = Path(git(repo, "rev-parse", "--show-toplevel").strip())
        except RuntimeError:
            return None
        forbid, allow = load_rules(top)
        if verb == "commit":
            return verb, check_commit(top, args, added, forbid, allow)
        return verb, check_push(top, args, forbid, allow)
    return None


def report(verb: str, findings: list[Finding]) -> str:
    lines = [f"commit-guard stopped this git {verb}:"]
    for f in findings:
        lines.append(f"  {f.kind:<8} {f.where}: {f.detail}")
    if any(f.kind in ("secret", "file") for f in findings):
        lines.append("Remove the secret or file from the change (unstage it, add it to .gitignore, load the value "
                     "from the environment). If it was pushed before, tell the user to revoke it. A line that is "
                     f"meant to stay can carry the comment '{ALLOW_MARK}'.")
    if any(f.kind == "message" for f in findings):
        lines.append("Write the message without the forbidden text." + (
            " The commits are not pushed yet: ask the user before rewording them (that rewrites history)."
            if verb == "push" else ""))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    if os.environ.get("TOOLKIT_COMMIT_GUARD", "").lower() in ("off", "0", "false"):
        return 0
    try:
        if argv and argv[0] in ("--commit", "--push"):
            verb = argv[0][2:]
            repo = Path(argv[1] if len(argv) > 1 else ".").resolve()
            top = Path(git(repo, "rev-parse", "--show-toplevel").strip())
            forbid, allow = load_rules(top)
            findings = (check_commit(top, [], False, forbid, allow) if verb == "commit"
                        else check_push(top, [], forbid, allow))
            print(report(verb, findings) if findings else f"commit-guard: nothing found in this {verb}.")
            return 1 if findings else 0
        event = json.load(sys.stdin)
        if event.get("tool_name") != "Bash":
            return 0
        command = (event.get("tool_input") or {}).get("command", "")
        if "git" not in command or not re.search(r"\b(commit|push)\b", command):
            return 0
        result = check_command(command, Path(event.get("cwd") or os.getcwd()))
    except Exception:  # noqa: BLE001 - never block work because the guard itself failed
        return 0
    if result and result[1]:
        print(report(*result), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
