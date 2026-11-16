"""Measure the tool definitions an MCP server loads into context, by starting it and asking (stdio servers only).

Used by context_cost.py --measure-mcp. Starting a server runs its program, so this only happens when asked.
Remote (HTTP/SSE) servers are listed, not measured.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from claude_home import claude_dir, read_json, tokens

PROTOCOL = "2025-06-18"


@dataclass
class Server:
    name: str
    origin: str               # plugin key, "project" or "user"
    config: dict
    plugin_root: Path | None = None


@dataclass
class Measured:
    server: Server
    tools: int = 0
    tokens: int = 0
    error: str = ""


def configured_servers(project: Path | None, plugins: list) -> list[Server]:
    out = [Server(name, p.key, cfg, p.path) for p in plugins if p.enabled for name, cfg in p.mcp.items()]
    if project is not None:
        for name, cfg in (read_json(project / ".mcp.json").get("mcpServers") or {}).items():
            out.append(Server(name, "project", cfg))
    user_cfg = read_json(Path.home() / ".claude.json") if not os.environ.get("CLAUDE_CONFIG_DIR") else \
        read_json(claude_dir() / ".claude.json")
    for name, cfg in (user_cfg.get("mcpServers") or {}).items():
        out.append(Server(name, "user", cfg))
    if project is not None:
        proj_cfg = (user_cfg.get("projects") or {}).get(str(project)) or {}
        for name, cfg in (proj_cfg.get("mcpServers") or {}).items():
            out.append(Server(name, "local", cfg))
    return out


def _expand(value: str, root: Path | None) -> str:
    if root is not None:
        value = value.replace("${CLAUDE_PLUGIN_ROOT}", str(root))
    return os.path.expandvars(value)


def measure(server: Server, timeout: float = 20) -> Measured:
    cfg = server.config
    if cfg.get("type") in ("http", "sse") or "url" in cfg:
        return Measured(server, error="remote server: not measured")
    command = cfg.get("command")
    if not command:
        return Measured(server, error="no command")
    argv = [_expand(command, server.plugin_root)] + [_expand(str(a), server.plugin_root) for a in cfg.get("args", [])]
    env = dict(os.environ)
    env.update({k: _expand(str(v), server.plugin_root) for k, v in (cfg.get("env") or {}).items()})
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                env=env, text=True, encoding="utf-8", errors="replace")
    except OSError as e:
        return Measured(server, error=f"could not start: {e}")

    result: dict = {}

    def talk():
        try:
            def send(msg):
                proc.stdin.write(json.dumps(msg) + "\n")
                proc.stdin.flush()

            def receive(want_id):
                for line in proc.stdout:
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if msg.get("id") == want_id:
                        return msg
                return None
            send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": PROTOCOL, "capabilities": {},
                "clientInfo": {"name": "niklas-toolkit-audit", "version": "0.5.0"}}})
            if not receive(1):
                result["error"] = "no answer to initialize"
                return
            send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            tools, cursor = [], None
            for page in range(20):
                send({"jsonrpc": "2.0", "id": 2 + page, "method": "tools/list",
                      "params": {"cursor": cursor} if cursor else {}})
                reply = receive(2 + page)
                if not reply or "result" not in reply:
                    result["error"] = (reply or {}).get("error", {}).get("message", "no answer to tools/list")
                    return
                tools += reply["result"].get("tools", [])
                cursor = reply["result"].get("nextCursor")
                if not cursor:
                    break
            result["tools"] = tools
        except (OSError, ValueError) as e:
            result["error"] = str(e)

    t = threading.Thread(target=talk, daemon=True)
    t.start()
    t.join(timeout)
    try:
        proc.kill()
    except OSError:
        pass
    if "tools" in result:
        tools = result["tools"]
        return Measured(server, len(tools), tokens(json.dumps(tools)))
    return Measured(server, error=result.get("error", f"no answer within {timeout:.0f} s"))
