import json
import subprocess
import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "packs" / "deps" / "scripts"))
import dep_audit  # noqa: E402
import licenses  # noqa: E402
import lockfiles  # noqa: E402
import osv  # noqa: E402
import registry  # noqa: E402
from netfake import install  # noqa: E402

POETRY_LOCK = """
[[package]]
name = "Requests"
version = "2.25.0"
description = "HTTP"

[package.dependencies]
urllib3 = ">=1.21"

[[package]]
name = "urllib3"
version = "1.26.4"

[metadata]
lock-version = "2.0"
"""

UV_LOCK = """
version = 1

[[package]]
name = "myproject"
version = "0.1.0"
source = { editable = "." }

[[package]]
name = "jinja2"
version = "2.10"
source = { registry = "https://pypi.org/simple" }
"""


@pytest.fixture
def project(tmp_path):
    (tmp_path / "requirements.txt").write_text(
        "# comment\nrequests==2.25.0 --hash=sha256:abc\nFlask[async]>=2.0 ; python_version > '3.8'\n"
        "-r dev-requirements.txt\n-e .\nhttps://example.com/x.whl\n", encoding="utf-8")
    (tmp_path / "dev-requirements.txt").write_text("pytest==7.0.0\n", encoding="utf-8")
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"lodash": "^4.17.15", "left-pad": "1.3.0"}}),
                                           encoding="utf-8")
    (tmp_path / "package-lock.json").write_text(json.dumps({"lockfileVersion": 3, "packages": {
        "": {"name": "demo"}, "node_modules/lodash": {"version": "4.17.15"},
        "node_modules/@scope/pkg": {"version": "2.0.0"}, "node_modules/linked": {"link": True}}}), encoding="utf-8")
    nm = tmp_path / "node_modules" / "x"
    nm.mkdir(parents=True)
    (nm / "package.json").write_text("{}", encoding="utf-8")  # must be skipped
    return tmp_path


def test_scan_requirements_and_npm(project):
    s = lockfiles.scan(project)
    got = {(p.ecosystem, p.name, p.version, p.direct) for p in s.packages}
    assert ("PyPI", "requests", "2.25.0", True) in got
    assert ("PyPI", "pytest", "7.0.0", True) in got          # via -r
    assert ("npm", "lodash", "4.17.15", True) in got          # locked version wins, marked direct by package.json
    assert ("npm", "@scope/pkg", "2.0.0", False) in got
    assert ("npm", "left-pad", "1.3.0", True) in got           # exact pin in package.json, not in the lockfile
    assert [p.name for p in s.unpinned] == ["flask"]
    assert not any("node_modules/x" in f for f in s.files)


@pytest.mark.parametrize("use_fallback", [False, True])
def test_toml_lockfiles(tmp_path, monkeypatch, use_fallback):
    if use_fallback:  # the Python 3.10 path
        monkeypatch.setattr(lockfiles, "tomllib", None)
    (tmp_path / "poetry.lock").write_text(POETRY_LOCK, encoding="utf-8")
    sub = tmp_path / "svc"
    sub.mkdir()
    (sub / "uv.lock").write_text(UV_LOCK, encoding="utf-8")
    names = {(p.name, p.version) for p in lockfiles.scan(tmp_path).packages}
    assert names == {("requests", "2.25.0"), ("urllib3", "1.26.4"), ("jinja2", "2.10")}  # editable project skipped


def test_other_ecosystems(tmp_path):
    (tmp_path / "Cargo.lock").write_text('[[package]]\nname = "serde"\nversion = "1.0.100"\n', encoding="utf-8")
    (tmp_path / "go.sum").write_text("golang.org/x/text v0.3.7 h1:abc=\ngolang.org/x/text v0.3.7/go.mod h1:def=\n",
                                     encoding="utf-8")
    (tmp_path / "composer.lock").write_text(json.dumps({"packages": [{"name": "monolog/monolog", "version": "v2.0.0"},
                                                                     {"name": "x/y", "version": "dev-main"}]}),
                                            encoding="utf-8")
    (tmp_path / "Gemfile.lock").write_text("GEM\n  remote: https://rubygems.org/\n  specs:\n    rack (2.2.3)\n"
                                           "    nokogiri (1.13.0-x86_64-linux)\n\nPLATFORMS\n  ruby\n", encoding="utf-8")
    (tmp_path / "yarn.lock").write_text('"chalk@^2.0.0", chalk@^2.4.1:\n  version "2.4.2"\n', encoding="utf-8")
    got = {(p.ecosystem, p.name, p.version) for p in lockfiles.scan(tmp_path).packages}
    assert got == {("crates.io", "serde", "1.0.100"), ("Go", "golang.org/x/text", "v0.3.7"),
                   ("Packagist", "monolog/monolog", "2.0.0"), ("RubyGems", "rack", "2.2.3"),
                   ("RubyGems", "nokogiri", "1.13.0"), ("npm", "chalk", "2.4.2")}


@pytest.mark.parametrize("vector,score", [
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", 9.8),
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H", 10.0),
    ("CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H", 7.8),
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N", 6.1),
    ("CVSS:3.0/AV:N/AC:H/PR:N/UI:R/S:U/C:L/I:N/A:N", 3.1),
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N", 0.0),
])
def test_cvss3(vector, score):
    assert osv.cvss3_base_score(vector) == score


def test_cvss_rejects_other_versions():
    assert osv.cvss3_base_score("CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N") is None


@pytest.mark.parametrize("a,b", [("1.0.0rc1", "1.0.0"), ("1.9", "1.10"), ("2.0.0-beta.1", "2.0.0"),
                                 ("1.0", "1.0.post1"), ("v1.2.3", "1.2.4")])
def test_version_order(a, b):
    assert registry.version_key(a) < registry.version_key(b)


def test_bump_kind_and_smallest_fix():
    assert registry.bump_kind("1.2.3", "2.0.0") == "major"
    assert registry.bump_kind("0.3.1", "0.4.0") == "major"   # 0.x minor can break
    assert registry.bump_kind("1.2.3", "1.3.0") == "minor"
    assert registry.bump_kind("1.2.3", "1.2.4") == "patch"
    assert registry.bump_kind("1.2.3", "1.2.3") == ""
    assert registry.smallest_fix("1.26.4", ["2.0.6", "1.26.17"]) == "1.26.17"
    assert registry.smallest_fix("3.0", ["2.0"]) == ""


@pytest.mark.parametrize("text,category", [
    ("MIT", "permissive"), ("Apache-2.0", "permissive"), ("GPL-3.0-only", "copyleft"),
    ("LGPL-2.1", "weak copyleft"), ("MIT OR GPL-3.0", "permissive"), ("MIT AND GPL-3.0", "copyleft"),
    ("", "unknown"), ("Proprietary-ish", "unknown"), ("AGPL-3.0", "copyleft"), ("MPL-2.0", "weak copyleft"),
])
def test_license_classes(text, category):
    assert licenses.classify(text) == category


GHSA = {"id": "GHSA-1111", "aliases": ["CVE-2020-1", "PYSEC-1"], "summary": "Bad thing",
        "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}],
        "affected": [{"package": {"ecosystem": "PyPI", "name": "requests"},
                      "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "2.31.0"}]}]}]}
PYSEC = {"id": "PYSEC-1", "aliases": ["GHSA-1111"], "summary": "Same bad thing"}
WITHDRAWN = {"id": "GHSA-2222", "withdrawn": "2024-01-01T00:00:00Z", "summary": "not real"}
LOW = {"id": "GHSA-3333", "summary": "Minor", "affected": [{"package": {"ecosystem": "PyPI", "name": "requests"},
       "database_specific": {"severity": "LOW"}, "ranges": [{"events": [{"fixed": "2.32.0"}]}]}]}


@pytest.fixture
def osv_net(monkeypatch, tmp_path):
    net = install(monkeypatch, tmp_path)

    def batch(req):
        queries = json.loads(req.data)["queries"]
        results = [{"vulns": [{"id": "GHSA-1111"}, {"id": "PYSEC-1"}, {"id": "GHSA-2222"}, {"id": "GHSA-3333"}]}
                   if q["package"]["name"] == "requests" else {} for q in queries]
        return 200, {}, json.dumps({"results": results}).encode()
    net.add("/v1/querybatch", batch)
    for doc in (GHSA, PYSEC, WITHDRAWN, LOW):
        net.add(f"/v1/vulns/{doc['id']}", doc)
    return net


def test_audit_dedupes_aliases_and_skips_withdrawn(osv_net):
    pkgs = [lockfiles.Package("PyPI", "requests", "2.25.0", "r.txt", True),
            lockfiles.Package("PyPI", "safe", "1.0", "r.txt", True)]
    findings = osv.audit(pkgs)
    assert len(findings) == 1
    ids = [v.id for v in findings[0].vulns]
    assert ids == ["GHSA-1111", "GHSA-3333"]          # PYSEC-1 is an alias, GHSA-2222 withdrawn
    assert findings[0].vulns[0].severity == "critical" and findings[0].vulns[0].score == 9.8
    assert findings[0].vulns[1].severity == "low"
    assert osv.audit(pkgs, ignore={"cve-2020-1"})[0].vulns[0].id == "GHSA-3333"  # ignore by alias


def test_dep_audit_cli(osv_net, project, capsys):
    assert dep_audit.main([str(project)]) == 1
    out = capsys.readouterr().out
    assert "requests 2.25.0  (PyPI, direct, requirements.txt)" in out
    assert "CRITICAL 9.8  GHSA-1111 (CVE-2020-1)  fixed in 2.31.0" in out
    assert "upgrading to 2.32.0 fixes all of these" in out
    assert "Not checked, no exact version (add a lockfile): flask" in out
    assert dep_audit.main([str(project), "--min-severity", "critical"]) == 1
    (project / "toolkit.json").write_text(json.dumps({"deps": {"ignore": ["GHSA-1111", "GHSA-3333"]}}),
                                          encoding="utf-8")
    assert dep_audit.main([str(project)]) == 0


def test_dep_audit_network_error_is_exit_2(monkeypatch, tmp_path, project, capsys):
    net = install(monkeypatch, tmp_path)
    net.add("/v1/querybatch", (503, {}, b"down"))
    assert dep_audit.main([str(project)]) == 2
    assert "OSV.dev answered HTTP 503" in capsys.readouterr().err


def test_outdated_and_licenses_cli(monkeypatch, tmp_path, project, capsys):
    import outdated
    net = install(monkeypatch, tmp_path)
    net.add("pypi.org/pypi/requests/json", {"info": {"version": "2.32.3", "license_expression": "Apache-2.0"}})
    net.add("pypi.org/pypi/pytest/json", {"info": {"version": "8.0.0", "license": "MIT"}})
    net.add("pypi.org/pypi/flask/json", {"info": {"version": "3.0.0", "classifiers": ["License :: OSI Approved :: BSD License"]}})
    net.add("registry.npmjs.org/lodash/latest", {"version": "4.17.21", "license": "MIT"})
    net.add("registry.npmjs.org/left-pad/latest", {"version": "1.3.0", "license": "WTFPL"})
    net.add("registry.npmjs.org/@scope%2Fpkg/latest", {"version": "2.0.0", "license": "GPL-3.0"})
    assert outdated.main([str(project)]) == 0
    out = capsys.readouterr().out
    assert "major  pytest" in out and "7.0.0 -> 8.0.0" in out
    assert "patch  lodash" in out
    assert "flask 3.0.0" in out
    assert licenses.main([str(project), "--fail-on", "copyleft"]) == 1
    assert "@scope/pkg 2.0.0  GPL-3.0" in capsys.readouterr().out


def test_deps_hook_reports_only_new(osv_net, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
    (repo / "requirements.txt").write_text("safe==1.0\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run([*git, "add", "."], cwd=repo, check=True)
    subprocess.run([*git, "commit", "-qm", "i"], cwd=repo, check=True)
    import deps_hook
    assert deps_hook.main(["--file", str(repo / "requirements.txt")]) == 0
    (repo / "requirements.txt").write_text("safe==1.0\nrequests==2.25.0\n", encoding="utf-8")
    assert deps_hook.main(["--file", str(repo / "requirements.txt")]) == 2
    assert deps_hook.main(["--file", str(repo / "notes.txt")]) == 0
