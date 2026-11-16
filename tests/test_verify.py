import json
import sys

from conftest import ROOT

sys.path.insert(0, str(ROOT / "packs" / "core" / "scripts"))
import verify  # noqa: E402

PY = f'"{sys.executable}"'


def write_cfg(path, checks):
    (path / "toolkit.json").write_text(json.dumps({"verify": checks}), encoding="utf-8")


def test_all_pass(tmp_path, capsys):
    write_cfg(tmp_path, [{"name": "a", "run": f"{PY} -c \"print('hi')\""}, {"name": "b", "run": f"{PY} -c \"\""}])
    assert verify.main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "PASS  a" in out and "PASS  b" in out and "hi" not in out  # output only shown on failure


def test_failure_shows_output_and_continues(tmp_path, capsys):
    write_cfg(tmp_path, [
        {"name": "bad", "run": f"{PY} -c \"import sys; print('boom'); sys.exit(3)\""},
        {"name": "good", "run": f"{PY} -c \"\""},
    ])
    assert verify.main([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "FAIL  bad" in out and "boom" in out and "[exit code 3]" in out
    assert "PASS  good" in out
    assert "FAILED: bad" in out


def test_fail_fast_and_only(tmp_path, capsys):
    write_cfg(tmp_path, [
        {"name": "bad", "run": f"{PY} -c \"import sys; sys.exit(1)\""},
        {"name": "good", "run": f"{PY} -c \"\""},
    ])
    assert verify.main([str(tmp_path), "--fail-fast"]) == 1
    assert "good" not in capsys.readouterr().out.split("FAIL  bad")[1].split("FAILED")[0]
    assert verify.main([str(tmp_path), "--only", "good"]) == 0


def test_timeout(tmp_path, capsys):
    write_cfg(tmp_path, [{"name": "slow", "run": f"{PY} -c \"import time; time.sleep(5)\"", "timeout": 1}])
    assert verify.main([str(tmp_path)]) == 1
    assert "timed out after 1s" in capsys.readouterr().out


def test_detects_npm_scripts(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "x", "lint": "y", "dev": "z"}}),
                                           encoding="utf-8")
    assert [c["run"] for c in verify.detect(tmp_path)] == ["npm run lint", "npm run test"]


def test_nothing_found(tmp_path, capsys):
    (tmp_path / ".git").mkdir()
    assert verify.main([str(tmp_path)]) == 2


def test_finds_root_from_subfolder(tmp_path, capsys):
    write_cfg(tmp_path, [{"name": "a", "run": f"{PY} -c \"\""}])
    sub = tmp_path / "src" / "deep"
    sub.mkdir(parents=True)
    assert verify.main([str(sub), "--list"]) == 0
    assert "1 check(s) from toolkit.json" in capsys.readouterr().out
