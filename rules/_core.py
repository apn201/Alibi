"""Shared plumbing for the rules: one ship's track on a 1-minute grid, geometry, event dicts.

Why a grid: AIS arrives every 2 s to 3 min depending on ship and speed, and our archive
cases are already one position per minute. Putting everything on minute bins (median per
bin, missing minutes stay NaN, nothing is interpolated) makes every rule's window arithmetic
the same for all sources, and a missing minute stays visibly missing.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import pandas as pd

KM_PER_DEG = 111.2


@dataclass
class Grid:
    """One ship, minute bins from t0 (epoch s of the first bin). NaN = nothing heard that minute."""
    t0: int
    sog: np.ndarray
    cog: np.ndarray
    lat: np.ndarray
    lon: np.ndarray
    raw: pd.DataFrame  # the cleaned input, for rules that need the real report times (gaps)

    def __len__(self):
        return len(self.sog)

    def time(self, i) -> int:
        return int(self.t0 + 60 * i)


def prepare(track: pd.DataFrame) -> Grid | None:
    t = track.dropna(subset=["time", "lat", "lon"]).sort_values("time")
    if len(t) < 3:
        return None
    t = t.assign(m=(t["time"] // 60).astype("int64"))
    g = t.groupby("m").agg(sog=("sog", "median"), lat=("lat", "median"), lon=("lon", "median"),
                           cog=("cog", "last"))
    idx = np.arange(g.index.min(), g.index.max() + 1)
    g = g.reindex(idx)
    return Grid(int(idx[0] * 60), g["sog"].to_numpy(float), g["cog"].to_numpy(float),
                g["lat"].to_numpy(float), g["lon"].to_numpy(float), t[["time", "lat", "lon", "sog", "cog"]])


def circ_std(deg: np.ndarray) -> float:
    """Circular standard deviation in degrees (NaN-safe). 0 = perfectly steady course."""
    d = np.radians(deg[~np.isnan(deg)])
    if len(d) < 3:
        return float("nan")
    r = min(np.hypot(np.cos(d).mean(), np.sin(d).mean()), 1 - 1e-12)
    return float(np.degrees(np.sqrt(-2 * np.log(r))))


def circ_mean(deg: np.ndarray) -> float:
    d = np.radians(deg[~np.isnan(deg)])
    return float(np.degrees(np.arctan2(np.sin(d).mean(), np.cos(d).mean())) % 360) if len(d) else float("nan")


def ang_diff(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def runs(mask: np.ndarray, max_hole: int = 0) -> list[tuple[int, int]]:
    """(first, last) index pairs of True runs, bridging holes of up to max_hole False entries."""
    idx = np.flatnonzero(mask)
    if len(idx) == 0:
        return []
    cuts = np.flatnonzero(np.diff(idx) > max_hole + 1)
    starts = np.r_[idx[0], idx[cuts + 1]]
    ends = np.r_[idx[cuts], idx[-1]]
    return list(zip(starts.tolist(), ends.tolist()))


def iso(t: float) -> str:
    return datetime.fromtimestamp(float(t), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def event(mmsi, etype: str, t_start: float, t_end: float, lat: float, lon: float, summary: dict) -> dict:
    """CandidateEvent dict. event_id is deterministic: the same track always gives the same ids."""
    key = f"{mmsi}|{iso(t_start)}|{etype}"
    ev = {"event_id": "ev-" + hashlib.sha1(key.encode()).hexdigest()[:12], "event_type": etype,
          "start_time": iso(t_start), "end_time": iso(t_end),
          "location": {"latitude": round(float(lat), 5), "longitude": round(float(lon), 5)},
          "baseline_summary": {k: (float(round(v, 3)) if isinstance(v, (float, np.floating)) else v) for k, v in summary.items()}}
    if mmsi is not None:
        ev["vessel_id"], ev["identifier_type"] = str(mmsi), "MMSI"
    return ev


def _t(s: str) -> float:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def merge(events: list[dict], max_gap_s: int = 600) -> list[dict]:
    """Merge events of the same type that overlap or lie within max_gap_s. Keeps the first's id and summary."""
    out: list[dict] = []
    for e in sorted(events, key=lambda e: (e["event_type"], e["start_time"])):
        p = out[-1] if out else None
        if p and p["event_type"] == e["event_type"] and _t(e["start_time"]) - _t(p["end_time"]) <= max_gap_s:
            if e["end_time"] > p["end_time"]:
                p["end_time"] = e["end_time"]
            for k, v in e["baseline_summary"].items():
                p["baseline_summary"].setdefault(k, v)
        else:
            out.append(e)
    return sorted(out, key=lambda e: e["start_time"])


def to_xy(lat, lon, lat0: float = 60.0, lon0: float = 24.0):
    """Local equirectangular km. Good to well under 1 % over the Gulf of Finland."""
    return ((np.asarray(lon) - lon0) * np.cos(np.radians(lat0)) * KM_PER_DEG,
            (np.asarray(lat) - lat0) * KM_PER_DEG)


def dist_to_polyline_km(lat, lon, line: list[tuple[float, float]]) -> np.ndarray:
    """Distance from each point to a polyline given as (lon, lat) vertices, km."""
    px, py = to_xy(lat, lon)
    pts = [to_xy(la, lo) for lo, la in line]
    best = np.full(np.shape(px), np.inf)
    for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
        dx, dy = x1 - x0, y1 - y0
        L2 = dx * dx + dy * dy
        u = np.clip(((px - x0) * dx + (py - y0) * dy) / L2, 0, 1) if L2 else 0.0
        best = np.minimum(best, np.hypot(px - (x0 + u * dx), py - (y0 + u * dy)))
    return best


CELL_DEG = 0.02  # about 2.2 km x 1.1 km at 60 N


def cell(lat: float, lon: float) -> tuple[int, int]:
    return (int(np.floor(lat / CELL_DEG)), int(np.floor(lon / CELL_DEG)))


def learn_stop_areas(fleet: pd.DataFrame, min_ships: int = 3, dwell_min: int = 20) -> set[tuple[int, int]]:
    """Places where ships habitually stop (berths, anchorages), learnt from traffic: grid cells where at
    least `min_ships` different ships each sat below 1 kn for `dwell_min` minutes or more. A cell and its
    8 neighbours count. `fleet` has mmsi, lat, lon, sog, one row per ship per minute. Optional input to
    detect(); a lone ship that stops somewhere nobody else does (a grounding) is never excluded by it."""
    f = fleet[fleet["sog"] < 1.0].dropna(subset=["lat", "lon"])
    if f.empty:
        return set()
    ci, cj = np.floor(f["lat"].to_numpy() / CELL_DEG).astype(int), np.floor(f["lon"].to_numpy() / CELL_DEG).astype(int)
    d = pd.DataFrame({"i": ci, "j": cj, "mmsi": f["mmsi"].to_numpy()}).groupby(["i", "j", "mmsi"]).size()
    ships = d[d >= dwell_min].reset_index().groupby(["i", "j"])["mmsi"].nunique()
    base = ships[ships >= min_ships].index.tolist()
    return {(i + a, j + b) for i, j in base for a in (-1, 0, 1) for b in (-1, 0, 1)}
