import json
import subprocess
import sys

import pytest

from conftest import ROOT

SERVER_DIR = ROOT / "packs" / "godot" / "servers" / "godot_index"
sys.path.insert(0, str(ROOT / "packs" / "godot" / "scripts"))

from godot_index import Index, parse_scene, scene_tree  # noqa: E402

SCENE = """\
[gd_scene load_steps=4 format=3 uid="uid://main0001"]

[ext_resource type="Script" path="res://main.gd" id="1_a"]
[ext_resource type="PackedScene" uid="uid://enemy0001" path="res://enemy.tscn" id="2_b"]
[ext_resource type="Texture2D" uid="uid://icon0001" path="res://art/icon.png" id="3_c"]

[node name="Main" type="Node2D"]
script = ExtResource("1_a")

[node name="UI" type="Control" parent="." groups=["hud"]]

[node name="Icon" type="TextureRect" parent="UI"]
texture = ExtResource("3_c")

[node name="Enemy" parent="." instance=ExtResource("2_b")]
"""


@pytest.fixture
def project(tmp_path):
    (tmp_path / "project.godot").write_text(
        '[application]\nrun/main_scene="res://main.tscn"\n\n[autoload]\n\nGame="*res://game.gd"\n', encoding="utf-8")
    (tmp_path / "main.tscn").write_text(SCENE, encoding="utf-8")
    (tmp_path / "main.gd").write_text("extends Node2D\n\nsignal died\n\nfunc take_damage(n: int) -> void:\n"
                                      "\tvar s = load(\"uid://sound0001\")\n", encoding="utf-8")
    (tmp_path / "main.gd.uid").write_text("uid://mainscript1\n", encoding="utf-8")
    (tmp_path / "game.gd").write_text("extends Node\nconst PROPS_DIR = \"res://art/props\"\n", encoding="utf-8")
    (tmp_path / "enemy.tscn").write_text('[gd_scene format=3 uid="uid://enemy0001"]\n\n'
                                         '[node name="Enemy" type="Node2D"]\n', encoding="utf-8")
    (tmp_path / "player.gd").write_text("class_name Player\nextends Node\n", encoding="utf-8")
    (tmp_path / "uses_player.gd").write_text("extends Node\nvar p: Player\n", encoding="utf-8")
    (tmp_path / "orphan.gd").write_text("class_name Orphan\nextends Node\n", encoding="utf-8")
    art = tmp_path / "art"
    (art / "props").mkdir(parents=True)
    for name, uid in [("icon.png", "icon0001"), ("unused.png", "unused001"), ("sound.wav", "sound0001"),
                      ("props/tree.png", "tree0001")]:
        (art / name).write_bytes(b"x")
        (art / f"{name}.import").write_text(f'[remap]\n\nimporter="texture"\nuid="uid://{uid}"\n', encoding="utf-8")
    ignored = tmp_path / "export"
    ignored.mkdir()
    (ignored / ".gdignore").write_text("", encoding="utf-8")
    (ignored / "junk.png").write_bytes(b"x")
    return tmp_path


def test_parse_scene():
    nodes, ext = parse_scene(SCENE)
    assert [n.name for n in nodes] == ["Main", "UI", "Icon", "Enemy"]
    assert nodes[0].script == "res://main.gd"
    assert nodes[1].groups == "hud"
    assert nodes[3].instance == "res://enemy.tscn"
    assert ext["3_c"] == "res://art/icon.png"


def test_scene_tree_indents_by_parent(project):
    lines = scene_tree(project, "res://main.tscn").splitlines()
    assert lines[1] == "Main (Node2D) script=res://main.gd"
    assert lines[2] == "  UI (Control) groups=[hud]"
    assert lines[3] == "    Icon (TextureRect)"
    assert lines[4] == "  Enemy [instance res://enemy.tscn]"


def test_usages_by_path_and_uid(project):
    idx = Index.build(project)
    assert idx.usages("res://art/icon.png") == [("res://main.tscn", 5)]
    assert idx.usages("art/sound.wav") == [("res://main.gd", 6)]  # referenced only through its uid
    assert idx.usages("uid://enemy0001") == [("res://main.tscn", 4)]
    assert idx.usages("res://enemy.tscn") == [("res://main.tscn", 4)]  # its own header uid is not a use


def test_symbol(project):
    idx = Index.build(project)
    assert idx.symbol("take_damage") == [("res://main.gd", 5, "func take_damage(n: int) -> void:")]
    assert idx.symbol("died")[0][:2] == ("res://main.gd", 3)
    assert idx.symbol("Player")[0][:2] == ("res://player.gd", 1)
    assert idx.symbol("Game") == [("res://project.godot", 6, 'autoload Game="*res://game.gd"')]


def test_unused(project):
    rows = dict(Index.build(project).unused())
    assert "res://art/unused.png" in rows and rows["res://art/unused.png"] == ""
    assert "res://orphan.gd" in rows                  # class_name nobody mentions
    assert "res://player.gd" not in rows              # used by its class_name
    assert "res://art/icon.png" not in rows
    assert "res://main.tscn" not in rows              # main scene, referenced from project.godot
    assert "res://export/junk.png" not in rows        # .gdignore folder is skipped
    assert "dynamically" in rows["res://art/props/tree.png"]


def rpc(messages):
    proc = subprocess.run([sys.executable, str(SERVER_DIR / "server.py")], capture_output=True, text=True,
                          input="".join(json.dumps(m) + "\n" for m in messages), timeout=60)
    return [json.loads(line) for line in proc.stdout.splitlines()]


def test_server_protocol(project):
    replies = rpc([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "godot_find_usages", "arguments": {"path": "res://art/icon.png", "project": str(project)}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "godot_scene_tree", "arguments": {"scene": "res://nope.tscn", "project": str(project)}}},
        {"jsonrpc": "2.0", "id": 5, "method": "does/not/exist"},
    ])
    assert [r["id"] for r in replies] == [1, 2, 3, 4, 5]  # the notification gets no reply
    assert replies[0]["result"]["protocolVersion"] == "2025-06-18"
    assert {t["name"] for t in replies[1]["result"]["tools"]} == {
        "godot_scene_tree", "godot_find_usages", "godot_find_symbol", "godot_unused_files", "godot_api"}
    version = json.loads((ROOT / "packs" / "godot" / ".claude-plugin" / "plugin.json").read_text())["version"]
    assert replies[0]["result"]["serverInfo"]["version"] == version
    assert "res://main.tscn:5" in replies[2]["result"]["content"][0]["text"]
    assert replies[3]["result"]["isError"] is True
    assert replies[4]["error"]["code"] == -32601
