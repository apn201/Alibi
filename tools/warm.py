"""Warm a freshly started ALIBI: run every replay case through the API once.

    python tools/warm.py [--api http://127.0.0.1:8601/api/v1]

The first assessment of a day opens that day's Copernicus files, and the service caches each
request's findings, so after this pass a case loads and its source keys switch in seconds.
Results are not stored (persist false). Waits for the API to come up.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://127.0.0.1:8601/api/v1")
    a = ap.parse_args()
    for _ in range(120):
        try:
            if httpx.get(f"{a.api}/health", timeout=5).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(5)
    seen = set()
    for d in (ROOT / "data" / "cases", ROOT / "snapshot" / "cases"):
        for f in sorted(d.glob("*.json")):
            if f.name == "index.json" or f.stem in seen:
                continue
            seen.add(f.stem)
            reqs = json.loads(f.read_text(encoding="utf-8")).get("requests", [])
            t = time.time()
            for i in range(0, len(reqs), 200):
                httpx.post(f"{a.api}/assessments/batch", json={"requests": reqs[i:i + 200], "persist": False,
                                                                 "options": {"include_evidence": True}}, timeout=900)
            print(f"{f.stem}: {len(reqs)} requests, {time.time() - t:.0f} s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
