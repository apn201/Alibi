"""Send a case's candidates to ALIBI over HTTP and record what comes back.

    python -m detector replay --case eagle_s_2024 --api http://127.0.0.1:8601/api/v1 [--sensitivity 0.5]
                              [--sources profile,sea_state,...]

This is the detector's only contact with ALIBI, and it is plain HTTP (httpx): no imports from `alibi/`.
Candidates are the case file's requests whose `min_tier` is within the sensitivity's tier (the case
holds the most sensitive set; see cases.py). Tries `POST /assessments/batch` once, falls back to one
call per candidate. Writes data/results/<case>__<config>.json and prints a summary table.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

import rules

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "data" / "cases"
RESULTS = ROOT / "data" / "results"


def _unwrap(body) -> list:
    if isinstance(body, list):
        return body
    for k in ("assessments", "results", "items"):
        if isinstance(body, dict) and isinstance(body.get(k), list):
            return body[k]
    return []


def post_all(client: httpx.Client, api: str, reqs: list[dict]) -> list[dict]:
    """Assessments in request order; a failed one becomes {"error": ...}."""
    try:
        r = client.post(f"{api}/assessments/batch", json={"requests": reqs})
        if r.status_code == 200:
            got = _unwrap(r.json())
            if len(got) == len(reqs):
                return got
    except httpx.HTTPError:
        pass
    out = []
    for q in reqs:
        try:
            r = client.post(f"{api}/assessments", json=q)
            if r.status_code == 202:  # asynchronous service: poll
                aid = r.json()["assessment_id"]
                for _ in range(60):
                    time.sleep(0.5)
                    g = client.get(f"{api}/assessments/{aid}")
                    if g.status_code == 200:
                        r = g
                        break
            out.append(r.json() if r.status_code == 200 else {"error": f"HTTP {r.status_code}: {r.text[:200]}"})
        except httpx.HTTPError as exc:
            out.append({"error": repr(exc)})
    return out


def summarise(case_id: str, sensitivity: float, results: list[dict]) -> dict:
    ok = [r for r in results if "error" not in r]
    m = [r.get("measures", {}) for r in ok]
    top = 0.75 - 0.5 * sensitivity  # BUILD.md: top band if X >= 0.75 - 0.5 s
    xs = [x["unexplained"] for x in m if x.get("unexplained") is not None]
    us = [x["unusual"] for x in m if x.get("unusual") is not None]
    return {"case": case_id, "candidates": len(results), "assessed": len(ok), "errors": len(results) - len(ok),
            "scored": len(xs), "top_band": sum(1 for x in xs if x >= top), "top_band_threshold": round(top, 3),
            "mean_unusual": round(sum(us) / len(us), 3) if us else None,
            "mean_unexplained": round(sum(xs) / len(xs), 3) if xs else None}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m detector replay")
    ap.add_argument("--case", required=True)
    ap.add_argument("--api", default="http://127.0.0.1:8601/api/v1")
    ap.add_argument("--sensitivity", type=float, default=0.5)
    ap.add_argument("--sources", help="comma-separated source ids (default: the service's default set)")
    ap.add_argument("--label", help="config name in the result file name (default: derived)")
    ap.add_argument("--limit", type=int, help="only the first N candidates (smoke test)")
    a = ap.parse_args(argv)

    case = json.loads((CASES / f"{a.case}.json").read_text(encoding="utf-8"))
    tier = rules.tier(a.sensitivity)
    reqs = [q for q in case["requests"] if q.get("metadata", {}).get("min_tier", 2) <= tier]
    if a.limit:
        reqs = reqs[: a.limit]
    opts = {"sensitivity": a.sensitivity}
    if a.sources:
        opts["enabled_sources"] = a.sources.split(",")
    for q in reqs:
        q["options"] = {**q.get("options", {}), **opts}
    label = a.label or f"s{a.sensitivity:g}_" + (a.sources.replace(",", "+") if a.sources else "default")
    api = a.api.rstrip("/")
    with httpx.Client(timeout=120) as client:
        try:
            client.get(f"{api}/health").raise_for_status()
        except httpx.HTTPError as exc:
            sys.exit(f"ALIBI not reachable at {api}: {exc!r}")
        t0 = time.time()
        results = post_all(client, api, reqs)
    RESULTS.mkdir(parents=True, exist_ok=True)
    summary = summarise(a.case, a.sensitivity, results)
    summary.update(config=label, sensitivity=a.sensitivity, sources=a.sources, seconds=round(time.time() - t0, 1))
    out = RESULTS / f"{a.case}__{label}.json"
    out.write_text(json.dumps({"summary": summary, "case_id": a.case, "event_ids": [q["event"]["event_id"] for q in reqs],
                               "results": results}, separators=(",", ":")), encoding="utf-8")
    f = lambda v: "-" if v is None else v
    print(f"{'case':28} {'cand':>5} {'ok':>4} {'err':>4} {'top band':>9} {'mean U':>7} {'mean X':>7}")
    print(f"{summary['case']:28} {summary['candidates']:5d} {summary['assessed']:4d} {summary['errors']:4d} "
          f"{summary['top_band']:9d} {f(summary['mean_unusual']):>7} {f(summary['mean_unexplained']):>7}")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
