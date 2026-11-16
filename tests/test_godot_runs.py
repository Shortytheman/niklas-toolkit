"""Tests that start Godot. They run when GODOT_BIN is set (or godot is on PATH) and are skipped otherwise."""
import os

import pytest

import run_report
import screenshot
from conftest import needs_godot

pytestmark = needs_godot


def test_clean_run(project_copy, capsys):
    assert run_report.main([str(project_copy("mini_project")), "--frames", "10"]) == 0
    assert "0 error(s)" in capsys.readouterr().out


def test_runtime_errors_are_reported(project_copy, capsys):
    code = run_report.main([str(project_copy("mini_project")), "--frames", "10", "--", "--fail"])
    out = capsys.readouterr().out
    assert code == 1
    assert "ERROR: deliberate error from main.gd" in out
    assert "res://main.gd:9 in _ready" in out
    assert "WARNING: deliberate warning from main.gd" in out


def test_check_finds_parse_errors(project_copy, capsys):
    code = run_report.main([str(project_copy("broken_project")), "--check"])
    out = capsys.readouterr().out
    assert code == 1
    assert 'Identifier "undefined_variable" not declared' in out
    assert "res://main.gd:6" in out


def test_runs_use_sandboxed_user_data(project_copy):
    project = project_copy("mini_project")
    run_report.main([str(project), "--frames", "5"])
    assert (project / ".godot" / "toolkit" / "userdata").is_dir()


@pytest.mark.skipif(os.environ.get("CI") == "true", reason="needs a display to render")
def test_screenshot(project_copy):
    project = project_copy("mini_project")
    assert screenshot.main([str(project), "--frames", "3,6"]) == 0
    shots = sorted(p.name for p in (project / ".godot" / "toolkit" / "shots").glob("shot_*.png"))
    assert shots == ["shot_00003.png", "shot_00006.png"]
