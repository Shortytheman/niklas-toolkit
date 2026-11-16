#!/usr/bin/env python3
"""godot-index: an MCP server (stdio) that answers structural questions about a Godot 4 project.

Standard library only: it speaks MCP's JSON-RPC over stdin/stdout itself, so installing the plugin is enough.

Tools:
  godot_scene_tree     node tree of a .tscn: types, scripts, instanced scenes, groups
  godot_find_usages    every file and line that references a resource (by res:// path or uid://)
  godot_find_symbol    where a class_name, func, signal, const, var, enum or autoload is defined
  godot_unused_files   resources nothing references, with a note when a dynamic load may still use them
  godot_api            exact engine API (signatures, properties, signals, enums) of the project's Godot version

The project is the `project` argument, else $CLAUDE_PROJECT_DIR, else the working directory: the folder that holds
project.godot, a parent of it, or a folder up to two levels below it.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import godot_api  # noqa: E402
from godot_index import Index, scene_tree  # noqa: E402


def _plugin_version() -> str:
    try:
        manifest = Path(__file__).resolve().parents[2] / ".claude-plugin" / "plugin.json"
        return json.loads(manifest.read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError):
        return "0.0.0"


SERVER_INFO = {"name": "godot-index", "version": _plugin_version()}
PROTOCOL_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]

PROJECT_PROP = {"type": "string", "description": "Godot project folder. Optional: defaults to the current project."}
TOOLS = [
    {
        "name": "godot_scene_tree",
        "description": "Node tree of a Godot scene (.tscn) with node types, attached scripts, instanced scenes "
                       "and groups. Faster and clearer than reading the .tscn file.",
        "inputSchema": {"type": "object", "properties": {
            "scene": {"type": "string", "description": "res:// path of the scene, e.g. res://ui/menu.tscn"},
            "project": PROJECT_PROP}, "required": ["scene"]},
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "godot_find_usages",
        "description": "Every file and line that references a resource (script, scene, texture, sound...), "
                       "matching both res:// paths and uid:// references. Use before renaming, moving or "
                       "deleting a resource.",
        "inputSchema": {"type": "object", "properties": {
            "path": {"type": "string", "description": "res:// path, uid://, or project-relative path"},
            "project": PROJECT_PROP}, "required": ["path"]},
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "godot_find_symbol",
        "description": "Where a GDScript name is defined: class_name, class, func, signal, const, var, enum, "
                       "or an autoload in project.godot.",
        "inputSchema": {"type": "object", "properties": {
            "name": {"type": "string", "description": "exact identifier, e.g. Player or take_damage"},
            "project": PROJECT_PROP}, "required": ["name"]},
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "godot_unused_files",
        "description": "Resources in a folder that no scene, script, resource or data file references. These are "
                       "candidates only: files in folders that code loads by building a path are listed "
                       "separately, and anything should be confirmed before deleting.",
        "inputSchema": {"type": "object", "properties": {
            "folder": {"type": "string", "description": "res:// folder to check (default res://)"},
            "include_dynamic": {"type": "boolean", "description": "also list files in folders loaded by "
                                                                  "building a path (default false)"},
            "project": PROJECT_PROP}},
        "annotations": {"readOnlyHint": True},
    },
]


API_TOOL = {
    "name": "godot_api",
    "description": "Exact Godot engine API for the project's Godot version: 'Class' (overview), "
                   "'Class.member' (signature, inherited members too), 'member' (classes that have it). Use "
                   "before writing engine calls you are not sure exist in this version; it flags Godot 3 names.",
    "inputSchema": {"type": "object", "properties": {
        "query": {"type": "string", "description": "e.g. Tween, Tween.tween_method, get_global_mouse_position"},
        "search": {"type": "boolean", "description": "list names containing the query text instead"},
        "full": {"type": "boolean", "description": "with a class: every signature"},
        "describe": {"type": "boolean", "description": "add the official description and deprecation notes"},
        "project": PROJECT_PROP}, "required": ["query"]},
    "annotations": {"readOnlyHint": True},
}
TOOLS.append(API_TOOL)


def find_project(hint: str | None) -> Path:
    start = Path(hint or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
    for d in [start, *start.parents]:
        if (d / "project.godot").is_file():
            return d
    below = sorted(start.glob("project.godot")) + sorted(start.glob("*/project.godot")) + \
        sorted(start.glob("*/*/project.godot"))
    if below:
        return below[0].parent
    raise ValueError(f"no Godot project (project.godot) found at or near {start}; pass the project argument")


def call_tool(name: str, args: dict) -> str:
    if name == "godot_api":
        try:
            project = find_project(args.get("project"))
        except ValueError:
            project = None          # no project: Godot from $GODOT_BIN or PATH
        try:
            return godot_api.answer(project, args["query"], full=bool(args.get("full")),
                                    find=bool(args.get("search")), desc=bool(args.get("describe")))
        except godot_api.NotFound as e:
            return str(e)
    project = find_project(args.get("project"))
    if name == "godot_scene_tree":
        return scene_tree(project, args["scene"])
    idx = Index.build(project)
    if name == "godot_find_usages":
        target = idx.resolve(args["path"])
        hits = idx.usages(target)
        if not hits:
            return f"No references to {target} found."
        return f"{len(hits)} reference(s) to {target}:\n" + "\n".join(f"{f}:{n}" for f, n in hits)
    if name == "godot_find_symbol":
        hits = idx.symbol(args["name"])
        if not hits:
            return f"No definition of {args['name']} found."
        return "\n".join(f"{f}:{n}: {text}" for f, n, text in hits)
    if name == "godot_unused_files":
        rows = idx.unused(args.get("folder") or "res://")
        sure = [r for r, note in rows if not note]
        maybe = [(r, note) for r, note in rows if note]
        lines = [f"{len(sure)} unreferenced file(s)" + (":" if sure else ".")] + sure
        if maybe:
            lines.append(f"\n{len(maybe)} more in folders that code loads by building a path"
                         + (":" if args.get("include_dynamic") else " (pass include_dynamic to list them)."))
            if args.get("include_dynamic"):
                lines += [f"{r}  ({note})" for r, note in maybe]
        return "\n".join(lines)
    raise ValueError(f"unknown tool {name}")


def handle(msg: dict) -> dict | None:
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return None  # notification (e.g. notifications/initialized): no reply
    if method == "initialize":
        asked = (msg.get("params") or {}).get("protocolVersion")
        version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        result = {"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": SERVER_INFO}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = msg.get("params") or {}
        try:
            text = call_tool(params.get("name", ""), params.get("arguments") or {})
            result = {"content": [{"type": "text", "text": text}], "isError": False}
        except (ValueError, FileNotFoundError, KeyError, godot_api.SetupError, godot_api.netlib.NetError) as e:
            result = {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}
        except Exception:  # noqa: BLE001 - report, never crash the server
            result = {"content": [{"type": "text", "text": traceback.format_exc(limit=3)}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main() -> None:
    stdin = open(sys.stdin.fileno(), encoding="utf-8", errors="replace", closefd=False)
    stdout = open(sys.stdout.fileno(), "w", encoding="utf-8", newline="\n", closefd=False)
    for line in stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            reply = handle(msg) if isinstance(msg, dict) else None
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()


if __name__ == "__main__":
    main()
