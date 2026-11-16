import json
import subprocess
import sys

import pytest

import gdscript_hook
from conftest import GODOT_SCRIPTS

pytestmark = pytest.mark.skipif(not gdscript_hook.gdtoolkit_available(), reason='needs: pip install "gdtoolkit==4.*"')

HOOK = GODOT_SCRIPTS / "gdscript_hook.py"
CLEAN_WITH_OLD_PROBLEM = "extends Node\n\n\nfunc _ready():\n\tvar x = 1\n\tif x:\n\t\treturn 1\n\telse:\n\t\treturn 2\n"


def git(repo, *args):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=repo, check=True,
                   capture_output=True)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / "a.gd").write_text(CLEAN_WITH_OLD_PROBLEM, encoding="utf-8")
    git(tmp_path, "add", "a.gd")
    git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def run_hook(path):
    event = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(path)}})
    return subprocess.run([sys.executable, str(HOOK)], input=event, capture_output=True, text=True)


def test_existing_problems_are_not_reported(repo):
    r = run_hook(repo / "a.gd")
    assert r.returncode == 0, r.stderr


def test_new_problems_are_reported(repo):
    (repo / "a.gd").write_text(CLEAN_WITH_OLD_PROBLEM + "\n\nfunc BadName():\n\tpass\n", encoding="utf-8")
    r = run_hook(repo / "a.gd")
    assert r.returncode == 2
    assert "BadName" in r.stderr
    assert "no-else-return" not in r.stderr  # it was there before the edit


def test_syntax_error_is_reported(repo):
    (repo / "a.gd").write_text("extends Node\n\nfunc _ready(:\n\tpass\n", encoding="utf-8")
    r = run_hook(repo / "a.gd")
    assert r.returncode == 2
    assert "line 3: syntax error" in r.stderr


def test_untracked_file_reports_everything(tmp_path):
    f = tmp_path / "new.gd"
    f.write_text("extends Node\n\n\nfunc BadName():\n\tpass\n", encoding="utf-8")
    r = run_hook(f)
    assert r.returncode == 2
    assert "BadName" in r.stderr


def test_disabled_rules_from_toolkit_json(repo):
    (repo / "project.godot").write_text("[application]\n", encoding="utf-8")
    (repo / "toolkit.json").write_text(json.dumps({"gdscript": {"disable": ["function-name"]}}), encoding="utf-8")
    (repo / "a.gd").write_text(CLEAN_WITH_OLD_PROBLEM + "\n\nfunc BadName():\n\tpass\n", encoding="utf-8")
    assert run_hook(repo / "a.gd").returncode == 0


def test_ignores_other_files_and_bad_input(tmp_path):
    (tmp_path / "x.txt").write_text("hi", encoding="utf-8")
    assert run_hook(tmp_path / "x.txt").returncode == 0
    r = subprocess.run([sys.executable, str(HOOK)], input="not json", capture_output=True, text=True)
    assert r.returncode == 0
