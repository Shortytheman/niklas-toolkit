import zipfile
from pathlib import Path

import pytest

import export
from export import Preset, bump, missing_template, read_presets, write_project_version, zip_build
from godot_common import read_project

PRESETS = """\
[preset.0]

name="windows"
platform="Windows Desktop"
export_path="export/windows/game.zip"
run_script="Expand-Archive
second line"

[preset.0.options]

custom_template/release=""
binary_format/embed_pck=false

[preset.1]

name="web"
platform="Web"

[preset.1.options]

custom_template/release="C:/does/not/exist.zip"
"""


@pytest.mark.parametrize("version,part,expected", [
    ("1.5.3", "patch", "1.5.4"),
    ("1.5.3", "minor", "1.6.0"),
    ("1.5.3", "major", "2.0.0"),
    ("1.0", "patch", "1.0.1"),
    ("", "minor", "0.1.0"),
])
def test_bump(version, part, expected):
    assert bump(version, part) == expected


def test_write_version_keeps_crlf(project_copy):
    project = project_copy("mini_project")
    path = project / "project.godot"
    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    write_project_version(project, "2.3.4")
    raw = path.read_bytes()
    assert b'config/version="2.3.4"\r\n' in raw
    assert b"\n" not in raw.replace(b"\r\n", b"")
    assert read_project(project).version == "2.3.4"


def test_write_version_inserts_when_missing(project_copy):
    project = project_copy("mini_project")
    path = project / "project.godot"
    path.write_text(path.read_text(encoding="utf-8").replace('config/version="0.1.0"\n', ""), encoding="utf-8")
    write_project_version(project, "1.0.0")
    assert read_project(project).version == "1.0.0"
    assert read_project(project).name == "Mini Project"


def test_read_presets(tmp_path):
    (tmp_path / "export_presets.cfg").write_text(PRESETS, encoding="utf-8")
    presets = read_presets(tmp_path)
    assert [(p.name, p.platform) for p in presets] == [("windows", "Windows Desktop"), ("web", "Web")]
    assert presets[0].options["binary_format/embed_pck"] == "false"


def test_missing_template(tmp_path):
    win = Preset("windows", "Windows Desktop", {})
    assert "export template missing" in missing_template(win, tmp_path, debug=False)
    (tmp_path / "windows_release_x86_64.exe").write_bytes(b"")
    assert missing_template(win, tmp_path, debug=False) is None
    assert "windows_debug_x86_64.exe" in missing_template(win, tmp_path, debug=True)

    web = Preset("web", "Web", {"custom_template/release": "C:/does/not/exist.zip"})
    assert "custom template not found" in missing_template(web, tmp_path, debug=False)
    assert missing_template(Preset("x", "SomeNewPlatform", {}), tmp_path, debug=False) is None


def test_templates_dir_uses_short_version(monkeypatch):
    assert export.templates_dir("4.7.2.stable.official.ed1daf0bf").name == "4.7.2.stable"


def test_zip_build_layout(tmp_path):
    build = tmp_path / "My Game"
    build.mkdir()
    (build / "My Game.exe").write_bytes(b"exe")
    (build / "My Game.pck").write_bytes(b"pck")
    readme = tmp_path / "HOW TO PLAY.txt"
    readme.write_text("play", encoding="utf-8")
    archive = zip_build(build, tmp_path / "out.zip", [readme])
    with zipfile.ZipFile(archive) as zf:
        assert sorted(zf.namelist()) == ["My Game/HOW TO PLAY.txt", "My Game/My Game.exe", "My Game/My Game.pck"]


def test_main_unknown_preset_is_setup_error(project_copy, tmp_path, capsys, monkeypatch):
    project = project_copy("mini_project")
    (project / "export_presets.cfg").write_text(PRESETS, encoding="utf-8")
    fake = tmp_path / "godot.exe"
    fake.write_bytes(b"")
    assert export.main([str(project), "--godot", str(fake), "--preset", "nope"]) == 2
    assert "unknown preset(s) ['nope']" in capsys.readouterr().err


def test_main_without_presets_is_setup_error(project_copy, tmp_path, capsys):
    fake = tmp_path / "godot.exe"
    fake.write_bytes(b"")
    assert export.main([str(project_copy("mini_project")), "--godot", str(fake)]) == 2
    assert "no presets" in capsys.readouterr().err


def git_repo(project):
    import subprocess
    for args in (["init", "-q"], ["add", "-A"], ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"]):
        subprocess.run(["git", *args], cwd=project, check=True, capture_output=True)


def test_write_checksum(tmp_path):
    import hashlib
    archive = tmp_path / "Game 1.0 windows.zip"
    archive.write_bytes(b"zip bytes")
    digest = export.write_checksum(archive)
    assert digest == hashlib.sha256(b"zip bytes").hexdigest()
    assert (tmp_path / "Game 1.0 windows.zip.sha256").read_text(encoding="utf-8") == f"{digest}  Game 1.0 windows.zip\n"


def test_check_can_tag(project_copy):
    project = project_copy("mini_project")
    with pytest.raises(export.SetupError, match="git repository"):
        export.check_can_tag(project, "v0.1.0")
    git_repo(project)
    export.check_can_tag(project, "v0.1.0")  # clean, no such tag: fine
    (project / "main.gd").write_text("extends Node2D\n", encoding="utf-8")
    with pytest.raises(export.SetupError, match="clean working tree"):
        export.check_can_tag(project, "v0.1.0")


def test_tag_release_commits_version_and_tags(project_copy, monkeypatch):
    import subprocess
    for var in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(var, "t")
    for var in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(var, "t@t")
    project = project_copy("mini_project")
    git_repo(project)
    export.write_project_version(project, "0.2.0")
    message = export.tag_release(project, "v0.2.0", "0.2.0", version_changed=True)
    assert message.startswith("tagged v0.2.0")
    log = subprocess.run(["git", "log", "--format=%s", "-1"], cwd=project, capture_output=True, text=True).stdout
    assert log.strip() == "Version 0.2.0"
    assert subprocess.run(["git", "status", "--porcelain"], cwd=project, capture_output=True, text=True).stdout == ""
    with pytest.raises(export.SetupError, match="already exists"):
        export.check_can_tag(project, "v0.2.0")
