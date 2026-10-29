"""Where do ships stop? Berths, anchorages and waiting areas learnt from AIS history.

    python tools/stop_areas.py [--dk-every 7]   -> data/derived/profile_db/stop_areas.parquet

A grid cell of 0.02 deg (rules._core.CELL_DEG, about 2.2 x 1.1 km) is a stop area when at least
MIN_SHIPS different merchant-size ships each sat below 1 kn in it for DWELL_MIN minutes or more.
Sources: every day of our Digitraffic recording, and every `dk-every`-th day of the Danish archive
(one position per ship per minute). A slowdown that ends in such a cell is most likely an arrival.

The place explainer reads the table (alibi/explainers/place.py). A single ship stopping where
nobody else ever stops is not explained by it, which keeps the grounding question open.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from alibi_lab import dma  # noqa: E402
from alibi_lab.load import CACHE  # noqa: E402
from rules._core import CELL_DEG  # noqa: E402

OUT = ROOT / "data" / "derived" / "profile_db" / "stop_areas.parquet"
OWN = ROOT / "data" / "derived" / "profile_db" / "own_stops.parquet"
OWN_DAYS = 2  # a ship's own berth: it stopped in the cell on at least this many different days
DWELL_MIN = 20
MIN_SHIPS = 3


def dwell(df: pd.DataFrame, minute: np.ndarray) -> pd.DataFrame:
    """(i, j, mmsi) -> stopped minutes, for rows below 1 kn. Measured as the time span, not as a count of
    reports: a moored ship reports only every few minutes (AIS class A at anchor: every 3 min)."""
    slow = df["sog"].to_numpy() < 1.0
    d = pd.DataFrame({"i": np.floor(df["lat"].to_numpy()[slow] / CELL_DEG).astype(np.int32),
                      "j": np.floor(df["lon"].to_numpy()[slow] / CELL_DEG).astype(np.int32),
                      "mmsi": df["mmsi"].to_numpy()[slow], "m": minute[slow]})
    g = d.groupby(["i", "j", "mmsi"])["m"]
    return (g.max() - g.min() + 1).rename("minutes").reset_index()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dk-every", type=int, default=7)
    a = ap.parse_args()
    parts = []
    dk_files = sorted((dma.ROOT / "positions").glob("*/aisdk-*.parquet"))[::a.dk_every]
    for f in dk_files:
        p = pd.read_parquet(f, columns=["ts", "mmsi", "lat", "lon", "sog"]).dropna()
        p = p[(p["mmsi"] >= 200_000_000) & (p["mmsi"] < 800_000_000)]
        d = dwell(p, (p["ts"].to_numpy() // 60))
        parts.append(d[d["minutes"] >= DWELL_MIN].assign(source="dk", day=f.stem[6:]))
    fi_files = sorted(CACHE.glob("ais-*.v1.loc.parquet"))
    for f in fi_files:
        p = pd.read_parquet(f, columns=["mmsi", "time", "lat", "lon", "sog"]).dropna()
        parts.append(dwell(p, p["time"].to_numpy() // 60).assign(source="fi", day=f.name[4:12]))
    d = pd.concat(parts, ignore_index=True)
    # Our recording is per hour file: a stop spanning hours is summed per day before the dwell test.
    d = d.groupby(["i", "j", "mmsi", "source", "day"], as_index=False)["minutes"].sum()
    d = d[d["minutes"] >= DWELL_MIN]
    cells = d.groupby(["i", "j"]).agg(ships=("mmsi", "nunique"), stops=("mmsi", "size"),
                                       minutes=("minutes", "sum"), sources=("source", lambda s: ",".join(sorted(set(s)))))
    cells = cells[cells["ships"] >= MIN_SHIPS].reset_index()
    cells["lat"] = (cells["i"] + 0.5) * CELL_DEG
    cells["lon"] = (cells["j"] + 0.5) * CELL_DEG
    OUT.parent.mkdir(parents=True, exist_ok=True)
    cells.to_parquet(OUT, index=False)
    # A ferry's own berth may be used by no other ship (Eckeroe's Berghamn): keep each ship's repeat stops too.
    own = d.groupby(["mmsi", "i", "j"])["day"].nunique().rename("days").reset_index()
    own = own[own["days"] >= OWN_DAYS]
    own.astype({"mmsi": "int64", "i": "int32", "j": "int32", "days": "int16"}).to_parquet(OWN, index=False)
    print(f"{len(own)} own repeat-stop cells for {own['mmsi'].nunique()} ships -> {OWN}")
    print(f"{len(cells)} stop cells from {len(dk_files)} Danish days and {len(fi_files)} recorded hours -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
