import json
import os
import sys
from pathlib import Path

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "packs" / "godot" / "scripts"))
import godot_api  # noqa: E402
from godot_common import RunOutput  # noqa: E402
from netfake import install  # noqa: E402

VERSION = "4.7.2.stable.official.ed1daf0bf"

OBJECT = """<?xml version="1.0" encoding="UTF-8" ?>
<class name="Object" api_type="core">
	<methods>
		<method name="get_instance_id" qualifiers="const"><return type="int" /></method>
		<method name="emit_signal" qualifiers="vararg"><return type="int" enum="Error" />
			<param index="0" name="signal" type="StringName" /></method>
	</methods>
	<signals><signal name="script_changed" /></signals>
</class>"""
NODE = """<?xml version="1.0" encoding="UTF-8" ?>
<class name="Node" inherits="Object" api_type="core">
	<methods>
		<method name="add_child">
			<return type="void" />
			<param index="1" name="force_readable_name" type="bool" default="false" />
			<param index="0" name="node" type="Node" />
		</method>
		<method name="get_children" qualifiers="const"><return type="Node[]" /></method>
	</methods>
	<members><member name="name" type="StringName" setter="set_name" getter="get_name" /></members>
	<constants>
		<constant name="PROCESS_MODE_INHERIT" value="0" enum="ProcessMode" />
		<constant name="NOTIFICATION_READY" value="13" />
	</constants>
</class>"""
SPRITE = """<?xml version="1.0" encoding="UTF-8" ?>
<class name="Sprite2D" inherits="Node" api_type="core">
	<members><member name="texture" type="Texture2D" setter="set_texture" getter="get_texture" /></members>
	<theme_items><theme_item name="outline" data_type="color" type="Color" default="Color(0, 0, 0, 1)" /></theme_items>
</class>"""
OFFICIAL_SPRITE = """<?xml version="1.0" encoding="UTF-8" ?>
<class name="Sprite2D" inherits="Node" deprecated="Use [Sprite3D] instead.">
	<brief_description>General-purpose sprite node.</brief_description>
	<description>
		Shows a [Texture2D]. Set [member texture] first.
		[codeblocks]
		[gdscript]
		func _ready():
			texture = load("res://icon.png")
		[/gdscript]
		[csharp]
		Texture = GD.Load("res://icon.png");
		[/csharp]
		[/codeblocks]
	</description>
	<members><member name="texture" type="Texture2D">The [Texture2D] to draw, see [method Node.add_child].</member></members>
</class>"""


def write_dump(dump: Path) -> None:
    (dump / "doc" / "classes").mkdir(parents=True)
    (dump / "modules" / "fx" / "doc_classes").mkdir(parents=True)
    (dump / "doc" / "classes" / "Object.xml").write_text(OBJECT, encoding="utf-8")
    (dump / "doc" / "classes" / "Node.xml").write_text(NODE, encoding="utf-8")
    (dump / "modules" / "fx" / "doc_classes" / "Sprite2D.xml").write_text(SPRITE, encoding="utf-8")
    (dump / "doc" / "other.xml").write_text("<x/>", encoding="utf-8")       # not a class file


@pytest.fixture
def idx(tmp_path):
    write_dump(tmp_path / "dump")
    return godot_api.build_index(tmp_path / "dump", VERSION)


def test_index_and_signatures(idx):
    assert set(idx["classes"]) == {"Object", "Node", "Sprite2D"}
    assert idx["classes"]["Sprite2D"]["file"] == "modules/fx/doc_classes/Sprite2D.xml"
    out = godot_api.lookup(idx, "Node.add_child()")
    assert out == "Node.add_child: func add_child(node: Node, force_readable_name: bool = false) -> void"
    assert "-> Array[Node] const" in godot_api.lookup(idx, "Node.get_children")
    assert "func emit_signal(signal: StringName, ...) -> Error" in godot_api.lookup(idx, "Object.emit_signal")
    assert "(inherited from Object)" in godot_api.lookup(idx, "Sprite2D.get_instance_id")
    assert "theme color outline: Color = Color(0, 0, 0, 1)" in godot_api.lookup(idx, "Sprite2D.outline")
    assert "const PROCESS_MODE_INHERIT = 0  (enum Node.ProcessMode)" in \
        godot_api.lookup(idx, "Node.PROCESS_MODE_INHERIT")
    assert godot_api.lookup(idx, "script_changed").startswith("script_changed is defined on 1 class(es)")


def test_class_overview(idx):
    out = godot_api.lookup(idx, "Sprite2D")
    assert out.startswith("class Sprite2D extends Node   (Godot 4.7.2.stable)")
    assert "Inherits: Node < Object" in out and "Properties (1): texture" in out
    node = godot_api.lookup(idx, "Node")
    assert "enum ProcessMode: PROCESS_MODE_INHERIT" in node and "Constants (1): NOTIFICATION_READY" in node
    assert "func add_child(" in godot_api.lookup(idx, "Node", full=True)


def test_not_found_suggests(idx):
    with pytest.raises(godot_api.NotFound) as e:
        godot_api.lookup(idx, "Node.instance")
    assert "Godot 3 name" not in str(e.value)          # only shown when the new name exists in this version
    idx["classes"]["Node"]["methods"]["instantiate"] = {"ret": "Node", "params": [], "q": ""}
    with pytest.raises(godot_api.NotFound) as e:
        godot_api.lookup(idx, "Node.instance")
    assert "Godot 3 name: use instantiate" in str(e.value)
    with pytest.raises(godot_api.NotFound) as e:
        godot_api.lookup(idx, "Node.add_chlid")
    assert "Did you mean: Node.add_child" in str(e.value)
    with pytest.raises(godot_api.NotFound) as e:
        godot_api.lookup(idx, "Object.texture")
    assert "texture exists on: Sprite2D" in str(e.value)
    with pytest.raises(godot_api.NotFound):
        godot_api.lookup(idx, "Nope.x")
    assert "Node.add_child" in godot_api.search(idx, "CHILD")


def test_version_tag_and_bbcode():
    assert godot_api.version_tag(VERSION) == "4.7.2-stable"
    assert godot_api.version_tag("4.3.stable.official.77dcf97d8") == "4.3-stable"
    assert godot_api.version_tag("4.5.0.beta2.official.x") == "4.5-beta2"
    assert godot_api.bbcode_to_text("Call [method Node.add_child] with [param node], see [Node].") == \
        "Call `Node.add_child` with `node`, see Node."


def test_describe_fetches_the_tagged_docs(idx, monkeypatch, tmp_path):
    fake = install(monkeypatch, tmp_path)
    fake.add("/4.7.2-stable/modules/fx/doc_classes/Sprite2D.xml", OFFICIAL_SPRITE)
    out = godot_api.describe(idx, "Sprite2D")
    assert out.startswith("DEPRECATED: Use Sprite3D instead.\nGeneral-purpose sprite node.")
    assert "func _ready():\n    texture = load" in out and "GD.Load" not in out
    assert "`Node.add_child`" in godot_api.describe(idx, "Sprite2D.texture")
    assert fake.count("Sprite2D.xml") == 1                         # the second lookup came from the cache


def test_load_index_dumps_once_per_version(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TOOLKIT_HOME", str(tmp_path / "home"))
    runs = []

    def fake_run(godot, args, timeout, cwd=None, env=None):
        runs.append(args)
        assert env["APPDATA"] != os.environ.get("APPDATA")       # never the user's editor settings
        write_dump(Path(args[-1]))
        return RunOutput(0, "", False, 1.0)

    monkeypatch.setattr(godot_api, "godot_version", lambda g: VERSION)
    monkeypatch.setattr(godot_api, "run_godot", fake_run)
    monkeypatch.setattr(godot_api, "find_godot", lambda explicit, project: Path("godot"))
    assert godot_api.main(["Node.add_child", "--project", str(tmp_path)]) == 0
    assert godot_api.main(["Node.nope", "--project", str(tmp_path)]) == 1
    assert len(runs) == 1 and runs[0][:2] == ["--headless", "--doctool"]
    cached = tmp_path / "home" / "godot-api" / VERSION / "index.json"
    assert json.loads(cached.read_text(encoding="utf-8"))["godot"] == VERSION
    assert "func add_child" in capsys.readouterr().out

    monkeypatch.setattr(godot_api, "run_godot", lambda *a, **k: RunOutput(1, "ERROR: boom", False, 1.0))
    assert godot_api.main(["Node", "--refresh", "--project", str(tmp_path)]) == 2
    assert "boom" in capsys.readouterr().err
