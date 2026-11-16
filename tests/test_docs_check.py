import json
import subprocess
import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "packs" / "core" / "scripts"))
import docs_check  # noqa: E402


@pytest.mark.parametrize("heading,slug", [
    ("Install", "install"), ("Per-project settings: `toolkit.json`", "per-project-settings-toolkitjson"),
    ("What's new in 0.4.0?", "whats-new-in-040"), ("[Link](x.md) heading", "link-heading"),
    ("Ünïcode Ok", "ünïcode-ok"),
])
def test_github_slug(heading, slug):
    assert docs_check.github_slug(heading) == slug


@pytest.fixture
def docs(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "build.py").write_text("", encoding="utf-8")
    (tmp_path / "docs" / "Guide.md").write_text("# Guide\n\n## Setup steps\n\n## Setup steps\n\n<a name=\"custom\"></a>\n",
                                                encoding="utf-8")
    (tmp_path / "README.md").write_text("\n".join([
        "# Project",
        "[ok](docs/Guide.md#setup-steps) [dup](docs/Guide.md#setup-steps-1) [html](docs/Guide.md#custom)",
        "[case](docs/guide.md) [gone](docs/missing.md) [anchor](docs/Guide.md#nope) [self](#project)",
        "[line](tools/build.py#L10) [mail](mailto:a@b.c) ![img](docs/pic.png)",
        "`[not a link](nowhere.md)`",
        "[ref]: docs/also-missing.md",
        "```bash",
        "python tools/build.py && python tools/old_build.py",
        "python ${CLAUDE_PLUGIN_ROOT}/scripts/fine.py   # variable paths are skipped",
        "[inside code](nowhere.md)",
        "```",
    ]), encoding="utf-8")
    return tmp_path


def test_finds_the_broken_ones(docs, capsys):
    assert docs_check.main([str(docs), "--json"]) == 1
    found = {(p["check"], p["target"]) for p in json.loads(capsys.readouterr().out)["problems"]}
    assert found == {
        ("missing-file", "docs/guide.md"),           # wrong case
        ("missing-file", "docs/missing.md"),
        ("missing-file", "docs/pic.png"),
        ("missing-file", "docs/also-missing.md"),
        ("missing-anchor", "docs/Guide.md#nope"),
        ("missing-script", "tools/old_build.py"),
    }


def test_case_hint(docs, capsys):
    docs_check.main([str(docs)])
    assert "docs/guide.md does not exist (exists with different letter case: Guide.md)" in capsys.readouterr().out


def test_git_ignored_docs_are_skipped(docs, capsys):
    subprocess.run(["git", "init", "-q"], cwd=docs, check=True)
    (docs / ".gitignore").write_text("notes/\n", encoding="utf-8")
    (docs / "notes").mkdir()
    (docs / "notes" / "x.md").write_text("[broken](nothing.md)", encoding="utf-8")
    docs_check.main([str(docs), "--json"])
    files = {p["file"] for p in json.loads(capsys.readouterr().out)["problems"]}
    assert "notes/x.md" not in files and "README.md" in files


def test_external_links(monkeypatch, docs, capsys):
    (docs / "README.md").write_text("[a](https://ok.test/) [b](https://gone.test/x) [c](https://shy.test/)",
                                    encoding="utf-8")
    answers = {"https://ok.test/": ("ok", "200"), "https://gone.test/x": ("dead", "HTTP 404"),
               "https://shy.test/": ("unknown", "HTTP 403")}
    monkeypatch.setattr(docs_check, "check_url", lambda url, timeout=10: answers[url])
    assert docs_check.main([str(docs), "--external", "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert [p["target"] for p in data["problems"]] == ["https://gone.test/x"]
    assert [u["url"] for u in data["unverified"]] == ["https://shy.test/"]


def test_clean_project(tmp_path, capsys):
    (tmp_path / "README.md").write_text("# Hi\n[top](#hi)\n", encoding="utf-8")
    assert docs_check.main([str(tmp_path)]) == 0
