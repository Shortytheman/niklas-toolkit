#!/usr/bin/env python3
"""Run every pack's trigger evals with `claude plugin eval` and write the results to docs/evals.md.

    python tools/run_evals.py                    all packs, 3 runs per case
    python tools/run_evals.py --pack godot --runs 1
    python tools/run_evals.py --summarize a.json b.json   only rebuild docs/evals.md from saved results

The cases live in packs/<pack>/evals/<case>/: a prompt phrased the way a user would ask (never naming the skill)
and a free grader that checks whether Claude loaded the expected skill, or loaded none for a nearby request
that should not trigger one. Runs use your Claude Code login (`claude /login` once in a terminal) and count
against your usage; graders call no judge model.

Exit codes: 0 every case passed, 1 a case failed or a run errored, 2 claude not found.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKS = ["core", "godot", "deps", "brief", "audit"]


def run_pack(pack: str, runs: int, out: Path) -> Path:
    cmd = ["claude", "plugin", "eval", ".", "--runs", str(runs), "--ablation", "none", "--no-publish",
           "--trust-plugin", "--json", str(out)]
    print(f"{pack}: {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, cwd=ROOT / "packs" / pack, check=False)
    return out


def rows(result: dict) -> list[dict]:
    plugin = (result.get("suite", {}).get("plugins") or [{}])[0].get("name", "?")
    out = []
    for case in result.get("cases", []):
        runs = case.get("arms", {}).get("with", [])
        passed = sum(1 for r in runs if r.get("passed"))
        errors = sorted({r["error"] for r in runs if r.get("error")})
        grader = (case.get("graders") or [{}])[0]
        expect = "no skill" if grader.get("config", {}).get("max") == 0 else \
            grader.get("config", {}).get("input_match", "").rsplit(")?", 1)[-1].strip('"')
        out.append({"pack": plugin, "case": case.get("name", "?"), "expects": expect, "passed": passed,
                    "runs": len(runs), "error": errors[0] if errors else ""})
    return out


def summarize(results: list[dict]) -> tuple[str, bool]:
    table = [r for res in results for r in rows(res)]
    total_runs = sum(r["runs"] for r in table)
    total_pass = sum(r["passed"] for r in table)
    version = next((res["claudeVersion"] for res in results if res.get("claudeVersion")), "?")
    lines = [
        "# Skill trigger evals", "",
        "Each case is a request phrased the way a user would type it, without naming the skill. A case passes when",
        "Claude loads the skill the request is meant for, or, for the \"no skill\" cases, when it loads none. Run",
        "them with `python tools/run_evals.py`; the cases live in `packs/<pack>/evals/`.", "",
        f"Last run: {date.today().isoformat()}, Claude Code {version}: **{total_pass}/{total_runs} runs passed** "
        f"across {len(table)} cases.", "",
        "| Pack | Case | Expects | Passed |", "| --- | --- | --- | --- |",
    ]
    for r in table:
        cell = f"{r['passed']}/{r['runs']}" + (f" (error: {r['error'][:60]})" if r["error"] else "")
        lines.append(f"| {r['pack']} | `{r['case']}` | {r['expects']} | {cell} |")
    ok = bool(table) and all(r["passed"] == r["runs"] and r["runs"] and not r["error"] for r in table)
    return "\n".join(lines) + "\n", ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the packs' trigger evals and write docs/evals.md.")
    ap.add_argument("--pack", action="append", choices=PACKS, help="only this pack (repeatable)")
    ap.add_argument("--runs", type=int, default=3, help="runs per case (default 3)")
    ap.add_argument("--summarize", nargs="+", metavar="JSON", help="only summarize saved result files")
    ap.add_argument("--out", default=str(ROOT / "docs" / "evals.md"), help="where to write the summary")
    a = ap.parse_args(argv)
    if a.summarize:
        files = [Path(p) for p in a.summarize]
    else:
        if not shutil.which("claude"):
            print("ERROR: claude not found on PATH", file=sys.stderr)
            return 2
        tmp = Path(tempfile.mkdtemp(prefix="toolkit-evals-"))
        files = [run_pack(p, a.runs, tmp / f"{p}.json") for p in (a.pack or PACKS)]
    results = [json.loads(f.read_text(encoding="utf-8")) for f in files if f.is_file()]
    text, ok = summarize(results)
    Path(a.out).write_text(text, encoding="utf-8")
    print(text)
    print(f"Wrote {a.out}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
