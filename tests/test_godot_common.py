import json

import pytest

from godot_common import (SetupError, digest_log, find_godot, find_project, load_toolkit_config,
                          parse_cfg_sections, read_project)


def test_parse_cfg_sections_handles_multiline_and_quotes():
    text = '[preset.0]\n\nname="windows"\nrun_script="line one\nline two"\nruns=true\n\n[preset.0.options]\n\na/b=1\n'
    s = parse_cfg_sections(text)
    assert s["preset.0"]["name"] == "windows"
    assert s["preset.0"]["run_script"] == "line one\nline two"
    assert s["preset.0"]["runs"] == "true"
    assert s["preset.0.options"]["a/b"] == "1"


def test_read_project(project_copy):
    info = read_project(project_copy("mini_project"))
    assert info.name == "Mini Project"
    assert info.version == "0.1.0"
    assert info.main_scene == "res://main.tscn"


def test_find_project_walks_up(project_copy):
    project = project_copy("mini_project")
    sub = project / "a" / "b"
    sub.mkdir(parents=True)
    assert find_project(sub) == project


def test_find_project_fails_outside_project(tmp_path):
    with pytest.raises(SetupError):
        find_project(tmp_path)


def test_toolkit_config_missing_and_invalid(tmp_path):
    assert load_toolkit_config(tmp_path) == {}
    (tmp_path / "toolkit.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(SetupError):
        load_toolkit_config(tmp_path)


def test_find_godot_accepts_download_folder(tmp_path, monkeypatch):
    monkeypatch.delenv("GODOT_BIN", raising=False)
    folder = tmp_path / "Godot_v4.7.2-stable_win64.exe"  # the Windows download is a folder with this name
    folder.mkdir()
    (folder / "Godot_v4.7.2-stable_win64.exe").write_bytes(b"")
    (folder / "Godot_v4.7.2-stable_win64_console.exe").write_bytes(b"")
    assert find_godot(str(folder)).name == "Godot_v4.7.2-stable_win64_console.exe"


def test_find_godot_from_toolkit_json(tmp_path, monkeypatch):
    monkeypatch.delenv("GODOT_BIN", raising=False)
    exe = tmp_path / "godot.exe"
    exe.write_bytes(b"")
    (tmp_path / "toolkit.json").write_text(json.dumps({"godot": str(exe)}), encoding="utf-8")
    assert find_godot(None, tmp_path) == exe


def test_find_godot_bad_path_is_setup_error(monkeypatch, tmp_path):
    monkeypatch.delenv("GODOT_BIN", raising=False)
    with pytest.raises(SetupError):
        find_godot(str(tmp_path / "nope.exe"))


RUN_LOG = """\
Godot Engine v4.7.2.stable.official.ed1daf0bf - https://godotengine.org

mini project ready
ERROR: deliberate error from main.gd
   at: push_error (core/variant/variant_utility.cpp:1023)
   GDScript backtrace (most recent call first):
       [0] _ready (res://main.gd:9)
ERROR: deliberate error from main.gd
   at: push_error (core/variant/variant_utility.cpp:1023)
   GDScript backtrace (most recent call first):
       [0] _ready (res://main.gd:9)
WARNING: deliberate warning from main.gd
   at: push_warning (core/variant/variant_utility.cpp:1033)
       [0] _ready (res://main.gd:10)
SCRIPT ERROR: Parse Error: Identifier "nope" not declared in the current scope.
   at: GDScript::reload (res://broken.gd:6)
\x1b[1;33mWARNING:\x1b[0m 23 ObjectDB instances were leaked at exit (run with `--verbose` for details).
   at: cleanup (core/object/object.cpp:2536)
"""


def test_digest_merges_repeats_and_keeps_project_locations():
    problems = digest_log(RUN_LOG)
    errors = [p for p in problems if p.kind == "error"]
    warnings = [p for p in problems if p.kind == "warning"]
    assert len(errors) == 2
    assert errors[0].message == "deliberate error from main.gd"
    assert errors[0].count == 2
    assert errors[0].context == ["res://main.gd:9 in _ready"]
    assert errors[1].message.startswith("Parse Error:")
    assert errors[1].context == ["res://broken.gd:6"]  # "in reload" is dropped for parse errors
    assert len(warnings) == 2
    assert warnings[1].context == ["at: cleanup (core/object/object.cpp:2536)"]  # engine-only: keep the at: line


def test_digest_ignore_patterns():
    problems = digest_log(RUN_LOG, ignore=["ObjectDB instances were leaked"])
    assert not any("ObjectDB" in p.message for p in problems)


def test_render_shows_count():
    p = digest_log(RUN_LOG)[0]
    assert p.render().splitlines() == ["ERROR: deliberate error from main.gd  (x2)", "    res://main.gd:9 in _ready"]
