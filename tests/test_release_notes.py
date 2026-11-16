import subprocess
import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "packs" / "core" / "scripts"))
import release_notes  # noqa: E402

GIT = ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]


def commit(repo, msg):
    (repo / "f.txt").write_text((repo / "f.txt").read_text(encoding="utf-8") + msg + "\n", encoding="utf-8")
    subprocess.run([*GIT, "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run([*GIT, "commit", "-qm", msg], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "f.txt").write_text("", encoding="utf-8")
    commit(tmp_path, "Initial")
    subprocess.run([*GIT, "tag", "-a", "v1.2.3", "-m", "v1.2.3"], cwd=tmp_path, check=True)
    return tmp_path


@pytest.mark.parametrize("subject,body,group", [
    ("feat(ui): add dark mode", "", "Added"), ("fix: crash on start", "", "Fixed"),
    ("feat!: drop Python 3.8", "", "Breaking"), ("refactor: split module", "BREAKING CHANGE: api", "Breaking"),
    ("Add export command", "", "Added"), ("Fix typo", "", "Fixed"), ("docs: readme", "", "Docs"),
    ("docs-check, fix_deps, more", "", "Other"), ("Improve speed", "", "Changed"), ("Whatever", "", "Other"),
])
def test_classify(subject, body, group):
    assert release_notes.classify(subject, body)[0] == group


def test_next_version():
    g = {k: [] for k in release_notes.GROUPS}
    assert release_notes.next_version("v1.2.3", dict(g, Fixed=[1])) == "1.2.4"
    assert release_notes.next_version("v1.2.3", dict(g, Added=[1])) == "1.3.0"
    assert release_notes.next_version("v1.2.3", dict(g, Breaking=[1])) == "2.0.0"
    assert release_notes.next_version("v0.4.0", dict(g, Breaking=[1])) == "0.5.0"
    assert release_notes.next_version(None, dict(g, Added=[1])) == ""


def test_dry_run_and_write(repo, capsys):
    commit(repo, "feat: new thing")
    commit(repo, "Fix the old thing")
    commit(repo, "Merge branch 'x'")
    commit(repo, "Bump v1.3.0")
    assert release_notes.main([str(repo)]) == 0
    out = capsys.readouterr().out
    assert "Suggested version: 1.3.0" in out and "### Added" in out and "- New thing (" in out
    assert "Merge branch" not in out and "Bump v1.3.0" not in out
    assert not (repo / "CHANGELOG.md").exists()
    (repo / "CHANGELOG.md").write_text("# Changelog\n\n## 1.2.3\n\n- old\n", encoding="utf-8")
    assert release_notes.main([str(repo), "--write"]) == 0
    text = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    assert text.startswith("# Changelog\n\n## 1.3.0 (") and text.index("## 1.3.0") < text.index("## 1.2.3")


def test_nothing_new_and_not_git(repo, tmp_path_factory, capsys):
    assert release_notes.main([str(repo)]) == 1
    outside = tmp_path_factory.mktemp("not-git")  # a separate folder: tmp_path itself is the repo
    assert release_notes.main([str(outside)]) == 2


def test_write_keeps_crlf(repo):
    commit(repo, "feat: thing")
    (repo / "CHANGELOG.md").write_bytes(b"# Changelog\r\n\r\n## 1.2.3\r\n\r\n- old\r\n")
    assert release_notes.main([str(repo), "--write"]) == 0
    raw = (repo / "CHANGELOG.md").read_bytes()
    assert b"## 1.3.0" in raw and b"\n" not in raw.replace(b"\r\n", b"")
