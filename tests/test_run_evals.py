import sys

from conftest import ROOT

sys.path.insert(0, str(ROOT / "tools"))
import run_evals  # noqa: E402


def case(name, match, runs):
    return {"name": name, "graders": [{"type": "tool_used", "config": match}],
            "arms": {"with": [{"passed": p, "error": e} for p, e in runs]}}


def test_summary_table_and_verdict():
    result = {"claudeVersion": "2.1.325", "suite": {"plugins": [{"name": "core"}]}, "cases": [
        case("verify-before-commit", {"tool": "Skill", "input_match": r'"skill"\s*:\s*"(?:[\w-]+:)?verify"'},
             [(True, ""), (True, "")]),
        case("no-skill", {"tool": "Skill", "min": 0, "max": 0}, [(True, ""), (False, "")]),
    ]}
    text, ok = run_evals.summarize([result])
    assert not ok
    assert "**3/4 runs passed** across 2 cases" in text
    assert "| core | `verify-before-commit` | verify | 2/2 |" in text
    assert "| core | `no-skill` | no skill | 1/2 |" in text
    errored = {"suite": {"plugins": [{"name": "deps"}]}, "cases": [
        case("x", {"tool": "Skill", "input_match": r'(?:[\w-]+:)?deps"'}, [(False, "exit 1: Not logged in")])]}
    text, ok = run_evals.summarize([errored])
    assert not ok and "(error: exit 1: Not logged in)" in text


def test_every_skill_has_a_trigger_case():
    skills = {(p.parents[2].name, p.parent.name) for p in ROOT.glob("packs/*/skills/*/SKILL.md")}
    covered = set()
    for grader in ROOT.glob("packs/*/evals/*/graders/skill-fired.md"):
        pack = grader.parents[3].name
        text = grader.read_text(encoding="utf-8")
        covered |= {(pack, s) for p, s in skills if p == pack and f'(?:[\\w-]+:)?{s}"' in text}
    assert skills - covered == set()
