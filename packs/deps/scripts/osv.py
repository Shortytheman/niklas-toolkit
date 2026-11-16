"""OSV.dev client and CVSS 3.x scoring. Standard library only; OSV needs no API key.

API: https://google.github.io/osv.dev/api/  (POST /v1/querybatch returns only ids; details come from /v1/vulns/{id})
"""
from __future__ import annotations

import math
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import netlib
from lockfiles import Package

API = "https://api.osv.dev/v1"
BATCH = 500           # queries per querybatch call (OSV accepts up to 1000)
DETAIL_TTL = 86400    # vulnerability details change rarely: cache a day
SEVERITY_ORDER = ["unknown", "low", "moderate", "high", "critical"]


@dataclass
class Vuln:
    id: str
    aliases: list[str]
    summary: str
    severity: str           # low | moderate | high | critical | unknown
    score: float | None     # CVSS 3.x base score when the advisory has a v3 vector
    fixed: list[str]        # versions that fix it, for this package
    url: str


@dataclass
class Finding:
    package: Package
    vulns: list[Vuln] = field(default_factory=list)

    @property
    def worst(self) -> str:
        return max((v.severity for v in self.vulns), key=SEVERITY_ORDER.index, default="unknown")


def query(packages: list[Package]) -> dict[Package, list[str]]:
    """Vulnerability ids per package, from as few querybatch calls as possible (paging included)."""
    out: dict[Package, list[str]] = {}
    pending = [(p, None) for p in packages if p.version]
    while pending:
        chunk, pending = pending[:BATCH], pending[BATCH:]
        queries = []
        for p, token in chunk:
            q = {"package": {"name": p.name, "ecosystem": p.ecosystem}, "version": p.version}
            if token:
                q["page_token"] = token
            queries.append(q)
        data = netlib.post_json(f"{API}/querybatch", {"queries": queries}, source="OSV.dev", timeout=60)
        for (p, _), result in zip(chunk, data.get("results", [])):
            ids = [v["id"] for v in (result or {}).get("vulns", []) or []]
            if ids:
                out.setdefault(p, []).extend(ids)
            if (result or {}).get("next_page_token"):
                pending.append((p, result["next_page_token"]))
    return out


def details(vuln_id: str) -> dict:
    return netlib.get_json(f"{API}/vulns/{vuln_id}", ttl=DETAIL_TTL, source="OSV.dev")


def audit(packages: list[Package], ignore: set[str] | None = None, workers: int = 8) -> list[Finding]:
    ignore = {i.upper() for i in (ignore or set())}
    hits = query(packages)
    all_ids = sorted({i for ids in hits.values() for i in ids})
    with ThreadPoolExecutor(max_workers=workers) as pool:
        docs = dict(zip(all_ids, pool.map(details, all_ids)))
    findings = []
    for pkg, ids in sorted(hits.items(), key=lambda kv: (kv[0].ecosystem, kv[0].name)):
        vulns = []
        seen: set[str] = set()
        for vid in ids:
            doc = docs.get(vid) or {}
            if doc.get("withdrawn"):
                continue
            names = {vid, *doc.get("aliases", [])}
            if names & seen or {n.upper() for n in names} & ignore:
                seen |= names
                continue  # same vulnerability under another id (GHSA / PYSEC / CVE), or ignored by the user
            seen |= names
            vulns.append(to_vuln(doc, pkg))
        if vulns:
            vulns.sort(key=lambda v: (-SEVERITY_ORDER.index(v.severity), v.id))
            findings.append(Finding(pkg, vulns))
    return findings


def to_vuln(doc: dict, pkg: Package) -> Vuln:
    severity, score = rate(doc)
    fixed = []
    for affected in doc.get("affected", []) or []:
        p = affected.get("package", {})
        if p.get("ecosystem", "").split(":")[0] != pkg.ecosystem:
            continue
        for rng in affected.get("ranges", []) or []:
            for event in rng.get("events", []) or []:
                if "fixed" in event and event["fixed"] not in fixed:
                    fixed.append(event["fixed"])
    cve = [a for a in doc.get("aliases", []) if a.startswith("CVE-")]
    vid = doc.get("id", "?")
    text = (doc.get("summary") or doc.get("details") or "").strip()
    summary = text.splitlines()[0][:160] if text else ""
    return Vuln(vid, cve, summary, severity, score, fixed, f"https://osv.dev/vulnerability/{vid}")


def rate(doc: dict) -> tuple[str, float | None]:
    """Severity from a CVSS 3.x vector when present, else the advisory database's own label."""
    for sev in doc.get("severity", []) or []:
        if sev.get("type") == "CVSS_V3":
            score = cvss3_base_score(sev.get("score", ""))
            if score is not None:
                return cvss_label(score), score
    labels = [str((a.get("database_specific") or {}).get("severity", "")) for a in doc.get("affected", []) or []]
    labels.append(str((doc.get("database_specific") or {}).get("severity", "")))
    for label in labels:
        label = label.lower()
        if label in ("low", "moderate", "medium", "high", "critical"):
            return ("moderate" if label == "medium" else label), None
    return "unknown", None


def cvss_label(score: float) -> str:
    if score >= 9.0:
        return "critical"
    if score >= 7.0:
        return "high"
    if score >= 4.0:
        return "moderate"
    return "low" if score > 0 else "unknown"


# CVSS v3.1 base metric weights (FIRST specification, section 7.4)
_W = {
    "AV": {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2},
    "AC": {"L": 0.77, "H": 0.44},
    "UI": {"N": 0.85, "R": 0.62},
    "C": {"H": 0.56, "L": 0.22, "N": 0.0},
    "I": {"H": 0.56, "L": 0.22, "N": 0.0},
    "A": {"H": 0.56, "L": 0.22, "N": 0.0},
}


def _roundup(x: float) -> float:
    """CVSS 3.1 Roundup: the smallest one-decimal number >= x, avoiding float artefacts."""
    i = round(x * 100000)
    return i / 100000.0 if i % 10000 == 0 else (math.floor(i / 10000) + 1) / 10.0


def cvss3_base_score(vector: str) -> float | None:
    if not re.match(r"^CVSS:3\.[01]/", vector or ""):
        return None
    m = dict(part.split(":", 1) for part in vector.split("/")[1:] if ":" in part)
    try:
        scope_changed = m["S"] == "C"
        pr = {"N": 0.85, "L": 0.68 if scope_changed else 0.62, "H": 0.5 if scope_changed else 0.27}[m["PR"]]
        iss = 1 - (1 - _W["C"][m["C"]]) * (1 - _W["I"][m["I"]]) * (1 - _W["A"][m["A"]])
        exploit = 8.22 * _W["AV"][m["AV"]] * _W["AC"][m["AC"]] * pr * _W["UI"][m["UI"]]
    except KeyError:
        return None
    impact = 7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15 if scope_changed else 6.42 * iss
    if impact <= 0:
        return 0.0
    if scope_changed:
        return _roundup(min(1.08 * (impact + exploit), 10))
    return _roundup(min(impact + exploit, 10))
