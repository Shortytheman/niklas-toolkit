import json

import doctor as doctor_cli
from godot_index import Index, doctor


def make_project(tmp_path):
    (tmp_path / "project.godot").write_text('[application]\nrun/main_scene="res://main.tscn"\n', encoding="utf-8")
    art = tmp_path / "art"
    art.mkdir()
    for name, uid in [("Hero.png", "hero0001"), ("enemy.png", "enemy001")]:
        (art / name).write_bytes(b"x")
        (art / f"{name}.import").write_text(f'[remap]\nuid="uid://{uid}"\n', encoding="utf-8")
    (tmp_path / "main.tscn").write_text(
        '[gd_scene format=3 uid="uid://main0001"]\n\n'
        '[ext_resource type="Texture2D" uid="uid://hero0001" path="res://art/Hero.png" id="1"]\n'
        '[ext_resource type="Texture2D" uid="uid://hero0001" path="res://art/enemy.png" id="2"]\n'
        '[ext_resource type="Texture2D" uid="uid://gone0001" path="res://art/enemy.png" id="3"]\n'
        '[ext_resource type="Script" path="res://missing.gd" id="4"]\n\n'
        '[node name="Main" type="Node2D"]\n', encoding="utf-8")
    (tmp_path / "main.gd").write_text(
        'extends Node\n'
        'const A = "res://art/hero.png"\n'          # wrong case
        'const B = "res://art/%s.png"\n'            # built at runtime: not checked
        'const C = "res://art/"\n'                  # folder prefix: not checked
        '# "res://commented/out.png"\n'             # still a reference, but commented: reported as broken
        'var t = load("uid://nobody01")\n'
        'var bb = "[img=16]res://art/enemy.png[/img] gold"\n', encoding="utf-8")  # BBCode: path ends at [
    return tmp_path


def by_check(findings):
    out = {}
    for f in findings:
        out.setdefault(f.check, []).append(f)
    return out


def test_doctor_checks(tmp_path):
    groups = by_check(doctor(Index.build(make_project(tmp_path))))
    broken = {f.message.split()[0] for f in groups["broken-path"]}
    assert "res://missing.gd" in broken
    assert "res://art/%s.png" not in broken
    assert [f.line for f in groups["wrong-case"]] == [2]
    assert "res://art/Hero.png" in groups["wrong-case"][0].message
    stale = groups["stale-uid"]
    assert len(stale) == 1 and "Godot loads res://art/Hero.png" in stale[0].message
    unknown = {f.message.split()[0] for f in groups["unknown-uid"]}
    assert unknown == {"uid://gone0001", "uid://nobody01"}
    assert "unused" not in groups


def test_doctor_unused_is_opt_in(tmp_path):
    project = make_project(tmp_path)
    (project / "sounds").mkdir()
    (project / "sounds" / "lonely.wav").write_bytes(b"x")
    (project / "art" / "maybe.png").write_bytes(b"x")  # art/ is a runtime path prefix in main.gd: not reported
    groups = by_check(doctor(Index.build(project), include_unused=True))
    # main.gd is unused too: main.tscn points at res://missing.gd instead
    assert [f.file for f in groups["unused"]] == ["res://main.gd", "res://sounds/lonely.wav"]


def test_cli_exit_codes_and_ignore(tmp_path, capsys):
    project = make_project(tmp_path)
    assert doctor_cli.main([str(project)]) == 1
    assert "wrong-case (1):" in capsys.readouterr().out

    (project / "toolkit.json").write_text(json.dumps({"doctor": {"ignore": [
        "missing.gd", "hero.png", "commented", "uid://"]}}), encoding="utf-8")
    assert doctor_cli.main([str(project)]) == 0
    assert "ignored by toolkit.json" in capsys.readouterr().out


def test_cli_clean_project(project_copy, capsys):
    assert doctor_cli.main([str(project_copy("mini_project"))]) == 0
    assert "0 error(s), 0 warning(s)" in capsys.readouterr().out


def test_cli_bad_config_is_setup_error(tmp_path, capsys):
    project = make_project(tmp_path)
    (project / "toolkit.json").write_text(r'{"doctor": {"ignore": ["a\.b"]}}', encoding="utf-8")  # bad JSON escape
    assert doctor_cli.main([str(project)]) == 2
    (project / "toolkit.json").write_text(json.dumps({"doctor": {"ignore": ["("]}}), encoding="utf-8")
    assert doctor_cli.main([str(project)]) == 2
    assert "bad pattern" in capsys.readouterr().err


def test_toolkit_json_is_not_scanned(tmp_path):
    project = make_project(tmp_path)
    (project / "toolkit.json").write_text(json.dumps({"doctor": {"ignore": ["res://nowhere/x.png"]}}),
                                          encoding="utf-8")
    assert "res://nowhere/x.png" not in Index.build(project).refs
