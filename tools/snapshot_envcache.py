"""Copy the demo-case days of the environmental cache into the repo as a compact snapshot (snapshot/envcache/).

Why: the server deploys by git clone, so the demo cases must travel with the repo. Same layout as data/envcache;
only the variables EnvCache reads, int16 with scale_factor/add_offset (per file and variable), zlib 9 + shuffle.
Verifies that EnvCache reads the snapshot within quantisation error, prints the total, and drops the oldest
recording days first if over the budget.

  python tools/snapshot_envcache.py [--src data/envcache] [--dst snapshot/envcache] [--max-mb 120]
"""
from __future__ import annotations

import argparse
import datetime as dt
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from alibi.env import fetch as F  # noqa: E402
from alibi.env.cache import KIND_VARS, EnvCache  # noqa: E402

SPANS = [  # region, first, last (UTC days); recording days are listed last-resort-first by date
    ("gof", "2024-12-25", "2024-12-25"), ("gof", "2026-10-05", "2026-10-06"),
    ("dk", "2025-10-03", "2025-10-06"), ("dk", "2026-07-02", "2026-07-04"), ("dk", "2026-02-01", "2026-02-07"),
]
RECORDING = ("gof", "2026-10-20", "2026-10-29")
KEEP = {ds: list(v[0]) for ds, v in F.DATASETS.items()}


def encode(src: Path, dst: Path) -> None:
    with xr.open_dataset(src) as ds:
        ds = ds.load()
    keep = [v for v in KEEP[dst.parents[1].name] if v in ds.data_vars]
    ds = ds[keep]
    enc = {}
    for v in keep:
        a = ds[v].values
        lo, hi = float(np.nanmin(a)), float(np.nanmax(a))
        scale = (hi - lo) / 65000 or 1.0
        enc[v] = {"dtype": "int16", "_FillValue": -32768, "scale_factor": scale, "add_offset": lo + 32767 * scale,
                  "zlib": True, "complevel": 9, "shuffle": True}
    dst.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(dst, encoding=enc)


def days(first: str, last: str):
    return [d.date() for d in pd.date_range(first, last, freq="D")]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    repo = Path(__file__).resolve().parents[1]
    ap.add_argument("--src", default=str(repo / "data" / "envcache"))
    ap.add_argument("--dst", default=str(repo / "snapshot" / "envcache"))
    ap.add_argument("--max-mb", type=float, default=120)
    a = ap.parse_args(argv)
    src, dst = Path(a.src), Path(a.dst)
    if dst.exists():
        shutil.rmtree(dst, ignore_errors=True)
    plan = [(r, d) for r, s, e in SPANS for d in days(s, e)]
    rec = [(RECORDING[0], d) for d in days(RECORDING[1], RECORDING[2])]  # oldest first
    plan += rec
    written: list[tuple[str, dt.date, list[Path]]] = []
    for region, d in plan:
        files = []
        for ds_id in F.DATASETS:
            p = F.day_path(src, ds_id, region, d)
            if p.exists():
                q = F.day_path(dst, ds_id, region, d)
                encode(p, q)
                files.append(q)
        written.append((region, d, files))
    size = lambda: sum(f.stat().st_size for _, _, fs in written for f in fs if f.exists())
    recording_days = {d for _, d in rec}
    for region, d, files in written:  # drop the oldest recording days first
        if size() <= a.max_mb * 1e6:
            break
        if d in recording_days:
            for f in files:
                f.unlink()
    n = sum(1 for _, _, fs in written for f in fs if f.exists())
    print(f"snapshot: {n} files, {size()/1e6:.1f} MB (budget {a.max_mb:.0f} MB) in {dst}")
    # verify: EnvCache on the snapshot vs the original within quantisation
    c0, c1 = EnvCache(src), EnvCache(dst)
    worst = 0.0
    for region, d, files in written:
        if not any(f.exists() for f in files):
            continue
        lo0, lo1, la0, la1 = F.REGIONS[region]
        t0 = int(pd.Timestamp(d).timestamp())
        pts = pd.DataFrame({"time": t0 + np.linspace(0, 82000, 60), "lat": np.linspace(la0 + .3, la1 - .3, 60),
                            "lon": np.linspace(lo0 + .5, lo1 - .5, 60)})
        r0, r1 = c0.sample_track(pts), c1.sample_track(pts)
        for col in r0.columns:
            both = r0[col].notna() & r1[col].notna()
            if (r0[col].notna() != r1[col].notna()).any():
                print(f"MISMATCH availability {region} {d} {col}")
                return 1
            if both.any():
                rng = max(float(r0[col][both].abs().max()), 1.0)
                worst = max(worst, float((r0[col][both] - r1[col][both]).abs().max()) / rng)
    print(f"max relative difference vs original: {worst:.5f}")
    return 0 if worst < 0.01 else 1


if __name__ == "__main__":
    raise SystemExit(main())
