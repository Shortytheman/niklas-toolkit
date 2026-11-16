import json
import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "packs" / "audit" / "scripts"))
import claude_home  # noqa: E402
import context_cost  # noqa: E402
import hook_doctor  # noqa: E402
import skill_usage  # noqa: E402


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A fake ~/.claude with one user-scope plugin, one plugin local to another project, and a session log."""
    claude = tmp_path / "claude"
    project = tmp_path / "proj"
    project.mkdir()
    plugin = tmp_path / "cache" / "demo"
    (plugin / "skills" / "alpha").mkdir(parents=True)
    (plugin / "skills" / "alpha" / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: " + "x" * 400 + "\n---\n\n" + "body " * 200, encoding="utf-8")
    (plugin / "skills" / "beta").mkdir()
    (plugin / "skills" / "beta" / "SKILL.md").write_text("---\nname: beta\ndescription: short\n---\nbody",
                                                         encoding="utf-8")
    (plugin / "agents").mkdir()
    (plugin / "agents" / "rev.md").write_text("---\nname: rev\ndescription: reviews\n---\nprompt", encoding="utf-8")
    (plugin / "hooks").mkdir()
    (plugin / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {"PostToolUse": [{"matcher": "Edit", "hooks": [
        {"type": "command", "command": "python \"${CLAUDE_PLUGIN_ROOT}/scripts/missing.py\"", "timeout": 5}]}]}}),
        encoding="utf-8")
    (plugin / ".mcp.json").write_text(json.dumps({"mcpServers": {"idx": {"command": "python"}}}), encoding="utf-8")
    other = tmp_path / "cache" / "other"
    (other / "skills" / "gamma").mkdir(parents=True)
    (other / "skills" / "gamma" / "SKILL.md").write_text("---\nname: gamma\ndescription: g\n---\n", encoding="utf-8")
    (claude / "plugins").mkdir(parents=True)
    (claude / "plugins" / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": {
        "demo@mk": [{"scope": "user", "installPath": str(plugin)}],
        "other@mk": [{"scope": "local", "projectPath": str(tmp_path / "elsewhere"), "installPath": str(other)}],
    }}), encoding="utf-8")
    (claude / "CLAUDE.md").write_text("# rules\n" + "rule\n" * 100, encoding="utf-8")
    (project / "CLAUDE.md").write_text("project rules", encoding="utf-8")
    logs = claude / "projects" / "p"
    logs.mkdir(parents=True)
    lines = [
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "demo:alpha"}}]}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "alpha"}}]}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Agent", "input": {"subagent_type": "rev"}}]}},
        {"type": "user", "message": {"content": "<command-name>/beta</command-name> go"}},
        {"type": "user", "message": {"content": "talking about Skill tools in plain text"}},
    ]
    (logs / "s1.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude))
    return claude, project


def test_frontmatter_and_tokens():
    meta, body = claude_home.frontmatter("---\nname: x\ndescription: \"hello\"\n---\nthe body")
    assert meta == {"name": "x", "description": "hello"} and body == "the body"
    assert claude_home.tokens("abcd" * 10) == 10


def test_installed_plugins_respect_scope(home):
    claude, project = home
    keys = [p.key for p in claude_home.installed_plugins(project)]
    assert keys == ["demo@mk"]          # other@mk is local to another project


def test_disabled_plugins(home):
    claude, project = home
    (project / ".claude").mkdir()
    (project / ".claude" / "settings.json").write_text(json.dumps({"enabledPlugins": {"demo@mk": False}}),
                                                       encoding="utf-8")
    assert [p.enabled for p in claude_home.installed_plugins(project)] == [False]


def test_context_cost(home, capsys):
    claude, project = home
    assert context_cost.main([str(project), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    demo = data["origins"]["demo@mk"]
    alpha = next(c for c in demo["components"] if c["name"] == "alpha")
    assert alpha["always"] > 100 and alpha["on_use"] > 200
    assert {c["name"] for c in demo["components"]} == {"alpha", "beta", "rev"}
    assert data["mcp_servers"] == [{"name": "idx", "plugin": "demo@mk"}]
    assert "user" in data["origins"] and "project" in data["origins"]   # the two CLAUDE.md files


def test_skill_usage(home, capsys):
    claude, project = home
    assert skill_usage.main([str(project), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["skills"] == {"demo:alpha": 1, "alpha": 1, "beta": 1}
    assert data["agents"] == {"rev": 1}
    assert data["never_used"] == []


def test_hook_doctor(home, tmp_path, capsys):
    claude, project = home
    (project / "hook.sh").write_bytes(b"echo hi\r\n")
    (claude / "settings.json").write_text(json.dumps({"hooks": {"Stop": [
        {"matcher": "(", "hooks": [{"type": "command", "command": "definitely-not-a-program-xyz --x | jq ."}]},
        {"hooks": [{"type": "command", "command": "bash hook.sh", "timeout": 3}]}]}}), encoding="utf-8")
    assert hook_doctor.main([str(project), "--json"]) == 1
    problems = json.loads(capsys.readouterr().out)["problems"]
    checks = {(p["check"], p["where"].split()[0]) for p in problems}
    assert ("bad-matcher", "user") in checks
    assert ("missing-program", "user") in checks
    assert ("crlf-script", "user") in checks
    assert ("missing-file", "demo@mk") in checks           # ${CLAUDE_PLUGIN_ROOT}/scripts/missing.py
    assert ("no-timeout", "user") in checks


def test_programs_in_shell_commands():
    assert hook_doctor.programs_in('FOO=1 python x.py && jq -r . | grep -q a; echo done') == \
        ["python", "jq", "grep"]
    assert hook_doctor.programs_in('if [ -f x ]; then node a.js; fi') == ["node"]


def test_store_stub_detection(tmp_path):
    stub = tmp_path / "WindowsApps" / "python3.exe"
    stub.parent.mkdir()
    stub.write_bytes(b"")
    assert hook_doctor.is_store_stub(str(stub))
    real = tmp_path / "bin" / "python3.exe"
    real.parent.mkdir()
    real.write_bytes(b"MZ")
    assert not hook_doctor.is_store_stub(str(real))
