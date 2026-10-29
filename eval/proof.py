"""Proof of value: the same cases, the same baseline, sources switched on one group at a time.

    python eval/proof.py [--api http://127.0.0.1:8601/api/v1] [--cases a,b]  -> eval/results/proof.json, proof.md

Runs, per alibi-plan.md "Proof of value":
    1  detector alone            how many candidates the demo detector raises
    2  + ALIBI, AIS-only         profile, own habit, place, fleet, position quality, identity
    3  + Copernicus              sea state and ice added
    4  + everything              notices added
    5  sensitivity sweep         0, 0.25, 0.5, 0.75, 1 with everything on
A candidate is in the top band when Unexplained >= 0.75 - 0.5 * sensitivity (docs/BUILD.md).
Talks to ALIBI only over HTTP, like any other client.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "data" / "cases"
OUT = ROOT / "eval" / "results"

AIS_ONLY = ["profile", "own_habit", "place", "fleet", "position_quality", "identity"]
RUNS = {
    "ais_only": AIS_ONLY,
    "copernicus": AIS_ONLY + ["sea_state", "ice"],
    "all": AIS_ONLY + ["sea_state", "ice", "notices"],
}
SWEEP = [0.0, 0.25, 0.5, 0.75, 1.0]


def top_band(x: float | None, s: float) -> bool:
    return x is not None and x >= 0.75 - 0.5 * s


def tier(s: float) -> int:
    return 0 if s < 0.4 else 1 if s < 0.8 else 2


def requests_at(case: dict, s: float) -> list[dict]:
    """The detector stores the most sensitive superset; keep what fires at this sensitivity."""
    out = []
    for r in case["requests"]:
        mt = ((r.get("event") or {}).get("baseline_summary") or {}).get("min_tier", 0)
        if mt <= tier(s):
            out.append(r)
    return out


def assess(api: str, reqs: list[dict], sources: list[str], s: float) -> list[dict]:
    opts = {"sensitivity": s, "enabled_sources": sources}
    with httpx.Client(timeout=300) as c:
        r = c.post(f"{api}/assessments/batch", json={"requests": reqs, "options": opts, "persist": False})
        if r.status_code == 404:
            return [c.post(f"{api}/assessments", json={**q, "options": opts}).json() for q in reqs]
        r.raise_for_status()
        body = r.json()
        return body["results"] if isinstance(body, dict) else body


def summary(results: list[dict], s: float) -> dict:
    scored = [r for r in results if r.get("measures", {}).get("unexplained") is not None]
    xs = [r["measures"]["unexplained"] for r in scored]
    us = [r["measures"]["unusual"] for r in scored]
    return {"candidates": len(results), "scored": len(scored),
            "top_band": sum(top_band(x, s) for x in xs),
            "mean_unusual": round(sum(us) / len(us), 3) if us else None,
            "mean_unexplained": round(sum(xs) / len(xs), 3) if xs else None}


def movers(before: list[dict], after: list[dict], s: float) -> list[dict]:
    """Candidates that left or entered the top band, with the findings that explain the change."""
    out = []
    for b, a in zip(before, after):
        xb, xa = b.get("measures", {}).get("unexplained"), a.get("measures", {}).get("unexplained")
        if top_band(xb, s) != top_band(xa, s):
            v = a.get("vessel") or {}
            out.append({"vessel": v.get("name") or (a.get("event") or {}).get("vessel_id"),
                        "event": (a.get("event") or {}).get("event_type"),
                        "start": (a.get("event") or {}).get("start_time"),
                        "unexplained": [xb, xa],
                        "why": [f["summary"] for f in a.get("findings", []) if f["status"] == "supports_explanation"]})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://127.0.0.1:8601/api/v1")
    ap.add_argument("--cases", default="")
    ap.add_argument("--sensitivity", type=float, default=0.5)
    a = ap.parse_args()
    names = [n for n in a.cases.split(",") if n] or [
        p.stem for p in sorted(CASES.glob("*.json")) if p.stem not in ("index",) and not p.stem.startswith("detector_")]
    s = a.sensitivity
    report = {"sensitivity": s, "cases": {}}
    for name in names:
        case = json.loads((CASES / f"{name}.json").read_text(encoding="utf-8"))
        reqs = requests_at(case, s)
        row = {"title": case.get("title"), "kind": case.get("kind"), "third_party": case.get("third_party", False),
               "detector_alone": {"candidates": len(reqs)}}
        res = {}
        for run, sources in RUNS.items():
            res[run] = assess(a.api, reqs, sources, s) if reqs else []
            row[run] = summary(res[run], s)
        row["moved_by_copernicus"] = movers(res["ais_only"], res["copernicus"], s)
        row["sweep"] = []
        for sw in SWEEP:
            rq = requests_at(case, sw)
            row["sweep"].append({"sensitivity": sw, "detector": len(rq),
                                 **summary(assess(a.api, rq, RUNS["all"], sw) if rq else [], sw)})
        report["cases"][name] = row
        print(f"{name}: detector {len(reqs)} | top band ais-only {row['ais_only']['top_band']} "
              f"-> +copernicus {row['copernicus']['top_band']} -> all {row['all']['top_band']}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "proof.json").write_text(json.dumps(report, indent=1), encoding="utf-8")

    md = [f"# Proof of value (sensitivity {s})\n",
          "| case | detector alone | top band, AIS-only | + Copernicus | + everything |", "|---|---|---|---|---|"]
    for n, r in report["cases"].items():
        md.append(f"| {r['title'] or n} | {r['detector_alone']['candidates']} | {r['ais_only']['top_band']} | "
                  f"{r['copernicus']['top_band']} | {r['all']['top_band']} |")
    md += ["", "## Sensitivity sweep, everything on\n", "| case | " + " | ".join(f"s={x}" for x in SWEEP) + " |",
           "|---|" + "---|" * len(SWEEP)]
    for n, r in report["cases"].items():
        md.append(f"| {r['title'] or n} | " + " | ".join(f"{w['detector']} / {w['top_band']}" for w in r["sweep"]) + " |")
    md.append("\nCells: detector candidates / top band.")
    for n, r in report["cases"].items():
        if r["moved_by_copernicus"]:
            md += [f"\n## {r['title'] or n}: moved by Copernicus\n"]
            for m in r["moved_by_copernicus"][:10]:
                md.append(f"- {m['vessel']} {m['event']} {m['start']}: {m['unexplained'][0]} -> {m['unexplained'][1]}. "
                          + " ".join(m["why"][:2]))
    (OUT / "proof.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
