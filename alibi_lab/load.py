"""Recorder hours -> pandas tables, cached per hour file as parquet.

    locations: rx, mmsi, time, lat, lon, sog, cog, heading, navStat, rot, posAcc, raim
    metadata:  rx, mmsi, timestamp, name, type, destination, draught, eta, imo, callSign, posType, refA..refD

AIS "not available" sentinels become NaN: sog 102.3, cog 360, heading 511, rot -128,
lat 91, lon 181. Units as received (sog knots, cog/heading degrees, draught 1/10 m).

Note, measured 2026-10-05: Digitraffic's location `time` is within 1 s of our receive
time `rx` for every message, so it is the feed's own stamp, not the ship's AIS
timestamp. It still orders a vessel's positions; it says nothing about radio latency.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "ais"
CACHE = ROOT / "data" / "derived" / "hours"
CACHE_VERSION = 1

LOC_COLS = ["time", "lat", "lon", "sog", "cog", "heading", "navStat", "rot", "posAcc", "raim"]
META_COLS = ["timestamp", "name", "type", "destination", "draught", "eta", "imo", "callSign",
             "posType", "refA", "refB", "refC", "refD"]
SENTINELS = {"sog": 102.3, "cog": 360.0, "heading": 511, "rot": -128, "lat": 91.0, "lon": 181.0}


def hour_files(root: Path = DATA, start: str | None = None, end: str | None = None) -> list[Path]:
    """Closed hour files (primary and sibling copies), sorted. start/end: 'YYYYMMDD-HH', inclusive."""
    files = sorted(Path(root).glob("*/*/*/ais-*.jsonl.gz"))
    keys = [(f.name[4:15], f) for f in files]
    return [f for k, f in keys if (start is None or k >= start) and (end is None or k <= end)]


def _parse(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    loc: dict[str, list] = {c: [] for c in ["rx", "mmsi", *LOC_COLS]}
    meta: dict[str, list] = {c: [] for c in ["rx", "mmsi", *META_COLS]}
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            try:
                msg = json.loads(line)
            except ValueError:
                continue  # a half line after a crash
            payload = msg.get("payload")
            parts = msg["topic"].split("/")
            if payload is None or len(parts) < 3 or not parts[1].isdigit():
                continue
            kind = parts[-1]
            if kind in ("location", "locations"):
                target, cols = loc, LOC_COLS
            elif kind == "metadata":
                target, cols = meta, META_COLS
            else:
                continue
            target["rx"].append(msg["rx"])
            target["mmsi"].append(int(parts[1]))
            for c in cols:
                target[c].append(payload.get(c))
    locations = pd.DataFrame(loc)
    for c, bad in SENTINELS.items():
        locations[c] = pd.to_numeric(locations[c], errors="coerce").astype("float64")
        locations.loc[locations[c] == bad, c] = np.nan
    locations.loc[locations["sog"] > 102.2, "sog"] = np.nan
    locations.loc[locations["cog"] >= 360, "cog"] = np.nan
    metadata = pd.DataFrame(meta)
    return locations, metadata


def load_hour(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    CACHE.mkdir(parents=True, exist_ok=True)
    stem = f"{path.name.removesuffix('.jsonl.gz')}.v{CACHE_VERSION}"
    loc_p, meta_p = CACHE / f"{stem}.loc.parquet", CACHE / f"{stem}.meta.parquet"
    if loc_p.exists() and meta_p.exists():
        return pd.read_parquet(loc_p), pd.read_parquet(meta_p)
    locations, metadata = _parse(path)
    locations.to_parquet(loc_p, index=False)
    metadata.to_parquet(meta_p, index=False)
    return locations, metadata


def load(start: str | None = None, end: str | None = None, root: Path = DATA) -> tuple[pd.DataFrame, pd.DataFrame]:
    """All closed hours in [start, end]. Duplicates removed: the same vessel at the same
    second and place (AIS repeats, overlapping recorder copies). Sorted by mmsi, time."""
    parts = [load_hour(f) for f in hour_files(root, start, end)]
    if not parts:
        raise FileNotFoundError(f"no closed hours in {root} for {start}..{end}")
    locations = pd.concat([p[0] for p in parts], ignore_index=True)
    metadata = pd.concat([p[1] for p in parts], ignore_index=True)
    n = len(locations)
    locations = locations.drop_duplicates(["mmsi", "time", "lat", "lon"]).sort_values(["mmsi", "time"],
                                                                                     ignore_index=True)
    locations.attrs["duplicates_removed"] = n - len(locations)
    locations["ts"] = pd.to_datetime(locations["time"], unit="s", utc=True)
    return locations, metadata


def vessels(metadata: pd.DataFrame) -> pd.DataFrame:
    """Latest metadata per vessel, plus a coarse ship-type group (ITU type codes)."""
    latest = metadata.sort_values("rx").groupby("mmsi").tail(1).set_index("mmsi")
    groups = {3: "fishing/tug/special", 4: "high speed", 5: "service", 6: "passenger",
              7: "cargo", 8: "tanker", 9: "other"}
    t = pd.to_numeric(latest["type"], errors="coerce")
    latest["group"] = (t // 10).map(groups).fillna("unknown")
    latest.loc[t.isin([30]), "group"] = "fishing"
    latest.loc[t.isin([31, 32, 52]), "group"] = "tug"
    latest.loc[t.isin([36, 37]), "group"] = "pleasure"
    return latest
