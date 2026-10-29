"""Live mode: the last 6 hours of our Digitraffic recording, as a case that refreshes itself.

    python -m detector live --ais-dir <recorder ais dir> [--every 600] [--once]

Reads the recorder's hour files (ais/YYYY/MM/DD/ais-YYYYMMDD-HH.jsonl[.gz], including the hour still
being written), runs the rules on merchant ships and writes data/cases/live_gof.json (kind "live")
atomically, then updates index.json. Same candidates-with-min_tier format as every other case, so the
GUI and `replay` treat it like any case. Gulf of Finland only: Denmark has no open live feed, only the
daily archive. `--once` runs a single pass (cron-friendly).

Closed (.gz) hours go through alibi_lab.load's parquet cache; the open hour is parsed fresh every pass,
and a half-written last line is skipped.
"""

from __future__ import annotations

import argparse
import gzip
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from . import cases as C

WINDOW_H = 6
LOAD_H = WINDOW_H + C.LOOKBACK_H  # context for the reference hour and the 6 h track of the oldest event
SPEC = dict(title="LIVE · Gulf of Finland", kind="live", region="gof", third_party=False, cap=None)


def _read_open(path: Path):
    """Parse a plain .jsonl hour (or any file) like alibi_lab.load._parse, tolerating a torn last line."""
    from alibi_lab import load as L
    loc: dict[str, list] = {c: [] for c in ["rx", "mmsi", *L.LOC_COLS]}
    meta: dict[str, list] = {c: [] for c in ["rx", "mmsi", *L.META_COLS]}
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            try:
                msg = json.loads(line)
                parts = msg["topic"].split("/")
                payload = msg.get("payload")
                if payload is None or len(parts) < 3 or not parts[1].isdigit():
                    continue
            except (ValueError, KeyError):
                continue
            kind = parts[-1]
            if kind in ("location", "locations"):
                target, cols = loc, L.LOC_COLS
            elif kind == "metadata":
                target, cols = meta, L.META_COLS
            else:
                continue
            target["rx"].append(msg["rx"])
            target["mmsi"].append(int(parts[1]))
            for c in cols:
                target[c].append(payload.get(c))
    import numpy as np
    locations = pd.DataFrame(loc)
    for c, bad in L.SENTINELS.items():
        locations[c] = pd.to_numeric(locations[c], errors="coerce").astype("float64")
        locations.loc[locations[c] == bad, c] = np.nan
    locations.loc[locations["sog"] > 102.2, "sog"] = np.nan
    locations.loc[locations["cog"] >= 360, "cog"] = np.nan
    return locations, pd.DataFrame(meta)


def load_recent(ais_dir: Path, now: float):
    from alibi_lab import load as L
    first = datetime.fromtimestamp(now - LOAD_H * 3600, timezone.utc).strftime("%Y%m%d-%H")
    files = {}
    for f in sorted(ais_dir.glob("*/*/*/ais-*.jsonl*")):
        if f.name.endswith(".sha256") or f.name[4:15] < first:
            continue
        key = f.name[4:15]
        if key not in files or f.suffix == ".gz":  # prefer the closed copy
            files[key] = f
    if not files:
        raise FileNotFoundError(f"no hour files under {ais_dir}")
    parts = [L.load_hour(f) if f.suffix == ".gz" else _read_open(f) for f in files.values()]
    loc = pd.concat([p[0] for p in parts], ignore_index=True)
    meta = pd.concat([p[1] for p in parts], ignore_index=True)
    loc = loc.drop_duplicates(["mmsi", "time", "lat", "lon"]).sort_values(["mmsi", "time"], ignore_index=True)
    return loc, meta


def run_once(ais_dir: Path) -> dict:
    now = time.time()
    loc, meta = load_recent(ais_dir, now)
    end = min(now, float(loc["time"].max()))  # the data's own edge, if the recorder is behind
    lo = end - WINDOW_H * 3600
    tracks, outages = C.merchant_minutes(loc, meta, end - LOAD_H * 3600, end, ais_dir)
    found = C.fleet_candidates(tracks, outages, lo, end + 1)
    spec = dict(SPEC, start=C.iso(lo), end=C.iso(end))
    row = C.write_case("live_gof", spec, found, tracks,
                       notes={"generated": C.iso(now), "window_h": WINDOW_H, "source": "own Digitraffic recording"})
    C.update_index(row)
    return row


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m detector live")
    ap.add_argument("--ais-dir", required=True, help="recorder data directory containing YYYY/MM/DD/ais-*.jsonl[.gz]")
    ap.add_argument("--every", type=int, default=600, help="seconds between passes (default 600)")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args(argv)
    ais_dir = Path(a.ais_dir)
    while True:
        t0 = time.time()
        try:
            row = run_once(ais_dir)
            print(f"{C.iso(time.time())} live_gof: {row['candidates_kept']} candidates {row['by_type']} "
                  f"({time.time() - t0:.0f} s)", flush=True)
        except Exception as exc:  # keep the previous file; try again next round
            print(f"{C.iso(time.time())} live pass failed: {exc!r}", flush=True)
            if a.once:
                raise
        if a.once:
            return
        time.sleep(max(1, a.every - (time.time() - t0)))
