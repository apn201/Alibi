"""The nightly job: new AIS days in, fresh profiles out, snapshot into the repo.

    python tools/nightly.py [--push] [--no-dma] [--no-copernicus]

Run by the Windows scheduled task "Alibi nightly profiles" (03:30 local), log in
data/derived/profile_db/nightly.log. Steps, each skipped quietly when it has nothing to do:

1. Danish archive: ingest every missing day up to yesterday (DMA publishes with a delay of a day
   or more; a day not yet published is tried again the next night). One worker: memory.
2. Our recording reaches data/ais through the hourly task "Alibi AIS pull" already.
3. Profiles: rebuild, leaving out windows that ALIBI assessed and could not explain
   (Unexplained >= 0.5 in the ledger): don't learn from what you flag.
4. Copernicus: fetch the last 3 days and the forecast into the cache.
5. snapshot/ refreshed; with --push committed and pushed, so a server can `git pull`.

Every assessment records the profile_version it used, so yesterday's results stay reproducible.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from alibi_lab import dma, profile_db  # noqa: E402

LOG = profile_db.DB / "nightly.log"
LEDGER = ROOT / "data" / "alibi-ledger.sqlite"
PY = sys.executable


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} {msg}\n")


def run(args: list[str]) -> int:
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}  # the Copernicus toolbox needs UTF-8
    p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    for line in (p.stdout + p.stderr).strip().splitlines()[-8:]:
        log("  " + line)
    return p.returncode


def flagged_windows(threshold: float = 0.5) -> pd.DataFrame:
    """Windows the service could not explain, from the audit ledger."""
    if not LEDGER.exists():
        return pd.DataFrame(columns=["mmsi", "start", "end"])
    rows = []
    with sqlite3.connect(LEDGER) as con:
        for (result,) in con.execute("select result from assessments"):
            r = json.loads(result)
            x = (r.get("measures") or {}).get("unexplained")
            mmsi = (r.get("vessel") or {}).get("mmsi")
            ev = r.get("event") or {}
            if x is None or x < threshold or not mmsi or not ev.get("start_time"):
                continue
            rows.append({"mmsi": int(mmsi),
                         "start": int(pd.Timestamp(ev["start_time"]).timestamp()),
                         "end": int(pd.Timestamp(ev["end_time"]).timestamp())})
    return pd.DataFrame(rows, columns=["mmsi", "start", "end"]).drop_duplicates()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--no-dma", action="store_true")
    ap.add_argument("--no-copernicus", action="store_true")
    a = ap.parse_args()
    log("START")
    try:
        if not a.no_dma:
            done = dma.done_days()
            last = max(date.fromisoformat(d) for d in done)
            yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
            if last < yesterday:
                log(f"dma: {last + timedelta(1)}..{yesterday}")
                run([PY, "tools/dma_ingest.py", str(last + timedelta(1)), str(yesterday), "--workers", "1"])
        flagged = flagged_windows()
        log(f"flagged windows from ledger: {len(flagged)}")
        profile_db.build(log=log, flagged=flagged)
        run([PY, "tools/stop_areas.py"])
        if not a.no_copernicus:
            run([PY, "tools/fetch_copernicus.py", "--recent", "3"])
        run([PY, "tools/snapshot.py"])
        if a.push:
            run(["git", "add", "snapshot"])
            if subprocess.run(["git", "diff", "--cached", "--quiet", "--", "snapshot"], cwd=ROOT).returncode:
                v = json.loads((ROOT / "snapshot" / "VERSION.json").read_text(encoding="utf-8"))["profile_version"]
                run(["git", "commit", "-m", f"Nightly profile snapshot {v}\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>",
                     "--", "snapshot"])
                run(["git", "push", "origin", "HEAD"])
    except Exception:
        log("FAILED " + traceback.format_exc())
        return 1
    log("END")
    return 0


if __name__ == "__main__":
    sys.exit(main())
