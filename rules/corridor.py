"""Corridor loiter: slow, or going round in circles, inside a cable or pipeline corridor.

Corridors are in `corridors.geojson`: approximate, schematic straight segments between
published landing points, each with an `uncertainty_km` buffer half-width. They are a
hand-made demo layer, not a cable register (see that file's comment and docs/detector.md).

A ship is "in" a corridor while it is within the buffer, ignoring holes of up to 5 min and
the 5 km around each end of a line (harbour approaches at the landings, where berthing is
normal). The visit is flagged when it lasts at least 30 / 20 / 12 min (tier 0 / 1 / 2) and either
  slow        median speed < 4 kn, or
  loitering   the path is curled: net displacement < half the distance sailed.
Tiers 0-1 skip visits inside learnt stop areas (berths, anchorages; see rules._core.learn_stop_areas).
A ship simply crossing at cruise speed is inside for a minute or two and never flagged.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from ._core import Grid, cell, dist_to_polyline_km, event, iso, runs, to_xy

LANDING_KM = 5.0
MIN_MIN = {0: 30, 1: 20, 2: 12}


@lru_cache(maxsize=1)
def corridors() -> list[dict]:
    gj = json.loads((Path(__file__).with_name("corridors.geojson")).read_text(encoding="utf-8"))
    return [{**f["properties"], "line": [tuple(c) for c in f["geometry"]["coordinates"]]} for f in gj["features"]]


def corridor_loiter(g: Grid, tier: int, mmsi=None, stops=None) -> list[dict]:
    valid = ~np.isnan(g.lat)
    if not valid.any():
        return []
    px, py = to_xy(g.lat, g.lon)
    out = []
    for c in corridors():
        d = np.full(len(g), np.inf)
        d[valid] = dist_to_polyline_km(g.lat[valid], g.lon[valid], c["line"])
        inside = d <= c["uncertainty_km"]
        for end_lon, end_lat in (c["line"][0], c["line"][-1]):  # harbour approaches at the landings
            ex, ey = to_xy(end_lat, end_lon)
            inside &= ~(np.hypot(px - ex, py - ey) <= LANDING_KM)
        for a, b in runs(inside, max_hole=5):
            minutes = b - a + 1
            if minutes < MIN_MIN[tier]:
                continue
            sog = g.sog[a : b + 1]
            x, y = to_xy(g.lat[a : b + 1], g.lon[a : b + 1])
            ok = ~np.isnan(x)
            if ok.sum() < 5:
                continue
            path = float(np.nansum(np.hypot(np.diff(x[ok]), np.diff(y[ok]))))
            net = float(np.hypot(x[ok][-1] - x[ok][0], y[ok][-1] - y[ok][0]))
            med = float(np.nanmedian(sog)) if not np.isnan(sog).all() else float("nan")
            slow = med < 4.0
            curled = path > 1.0 and net < 0.5 * path
            if not (slow or curled):
                continue
            if tier < 2 and stops is not None and cell(float(np.nanmedian(g.lat[a : b + 1])),
                                                       float(np.nanmedian(g.lon[a : b + 1]))) in stops:
                continue  # sitting in a berth or anchorage that happens to touch the buffer
            out.append(event(mmsi, "corridor_loiter", g.time(a), g.time(b) + 60, float(np.nanmedian(g.lat[a : b + 1])),
                             float(np.nanmedian(g.lon[a : b + 1])),
                             {"rule": "slow_in_corridor" if slow else "curled_path_in_corridor", "corridor": c["name"],
                              "corridor_id": c["id"], "observed_kn": med, "reference_kn": 4.0,
                              "minutes_inside": minutes, "min_distance_km": float(np.nanmin(d[a : b + 1])),
                              "uncertainty_km": c["uncertainty_km"], "detected_at": iso(g.time(a) + 60 * MIN_MIN[tier])}))
    return out
