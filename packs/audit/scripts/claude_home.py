"""Read what is installed in Claude Code: plugins, skills, agents, commands, hooks, MCP servers, CLAUDE.md files.

Standard library only, read-only. The Claude Code folder is $CLAUDE_CONFIG_DIR or ~/.claude.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path


def claude_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def frontmatter(text: str) -> tuple[dict, str]:
    """YAML-ish frontmatter (simple `key: value` lines) and the body after it."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        kv = re.match(r"^([\w-]+):\s*(.*)$", line)
        if kv:
            meta[kv.group(1)] = kv.group(2).strip().strip('"').strip("'")
    return meta, m.group(2)


def tokens(text: str) -> int:
    """Rough token count: about 4 characters per token for English text and code."""
    return (len(text) + 3) // 4


@dataclass
class Component:
    kind: str          # skill | agent | command | claude-md | mcp-server
    name: str
    origin: str        # plugin name@marketplace, "user", "project"
    path: Path
    always: int        # tokens loaded into every session (name + description, or the whole CLAUDE.md)
    on_use: int = 0    # tokens added when it is used (the skill body)


@dataclass
class Plugin:
    key: str           # name@marketplace
    path: Path
    scope: str
    project: str = ""
    enabled: bool = True
    components: list[Component] = field(default_factory=list)
    hooks: dict = field(default_factory=dict)
    mcp: dict = field(default_factory=dict)


def _plugin_components(root: Path, origin: str) -> list[Component]:
    out = []
    for skill in sorted(root.glob("skills/*/SKILL.md")):
        meta, body = frontmatter(skill.read_text(encoding="utf-8", errors="replace"))
        name = meta.get("name", skill.parent.name)
        out.append(Component("skill", name, origin, skill, tokens(name + meta.get("description", "")) + 8,
                             tokens(body)))
    for kind, pattern in (("agent", "agents/*.md"), ("command", "commands/*.md")):
        for f in sorted(root.glob(pattern)):
            meta, body = frontmatter(f.read_text(encoding="utf-8", errors="replace"))
            name = meta.get("name", f.stem)
            out.append(Component(kind, name, origin, f, tokens(name + meta.get("description", "")) + 8,
                                 tokens(body)))
    return out


def _enabled_map(project: Path | None) -> dict[str, bool]:
    """enabledPlugins from user, project and local settings (later files win)."""
    files = [claude_dir() / "settings.json"]
    if project:
        files += [project / ".claude" / "settings.json", project / ".claude" / "settings.local.json"]
    enabled: dict[str, bool] = {}
    for f in files:
        enabled.update(read_json(f).get("enabledPlugins", {}) or {})
    return enabled


def installed_plugins(project: Path | None = None) -> list[Plugin]:
    """Plugins that apply to `project` (user-scope ones always; project/local ones only for their project)."""
    data = read_json(claude_dir() / "plugins" / "installed_plugins.json")
    enabled = _enabled_map(project)
    out = []
    for key, entries in (data.get("plugins") or {}).items():
        for e in entries if isinstance(entries, list) else [entries]:
            proj = e.get("projectPath", "")
            scope = e.get("scope", "user")
            if scope != "user":
                if project is None or not proj or Path(proj).resolve() != project.resolve():
                    continue
            path = Path(e.get("installPath", ""))
            if not path.is_dir():
                continue
            p = Plugin(key, path, scope, proj, enabled.get(key, True))
            p.components = _plugin_components(path, key)
            p.hooks = read_json(path / "hooks" / "hooks.json").get("hooks", {}) or {}
            p.mcp = read_json(path / ".mcp.json").get("mcpServers", {}) or {}
            out.append(p)
    return out


def claude_md_files(project: Path | None) -> list[Path]:
    files = [claude_dir() / "CLAUDE.md"]
    if project:
        files += [project / "CLAUDE.md", project / "CLAUDE.local.md", project / ".claude" / "CLAUDE.md"]
        for parent in project.parents:  # CLAUDE.md files in parent folders are loaded too
            files.append(parent / "CLAUDE.md")
    return [f for f in files if f.is_file()]


def loose_components(project: Path | None) -> list[Component]:
    """Skills, agents and commands outside plugins: ~/.claude/... and <project>/.claude/..."""
    out = _plugin_components(claude_dir(), "user")
    if project:
        out += _plugin_components(project / ".claude", "project")
    for f in claude_md_files(project):
        out.append(Component("claude-md", str(f), "user" if claude_dir() in f.parents else "project", f,
                             tokens(f.read_text(encoding="utf-8", errors="replace"))))
    return out


def settings_hooks(project: Path | None) -> list[tuple[str, dict]]:
    """(source label, hooks dict) from settings files."""
    files = [("user settings", claude_dir() / "settings.json")]
    if project:
        files += [("project settings", project / ".claude" / "settings.json"),
                  ("local settings", project / ".claude" / "settings.local.json")]
    return [(label, read_json(f).get("hooks", {}) or {}) for label, f in files if f.is_file()]


def transcripts(days: int | None = None) -> list[Path]:
    import time
    root = claude_dir() / "projects"
    cutoff = time.time() - days * 86400 if days else 0
    return sorted(f for f in root.glob("*/*.jsonl") if f.stat().st_mtime >= cutoff)
