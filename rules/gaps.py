"""AIS gap: a ship that was moving and in good coverage stops being heard for > 15 min.

Three guards against the wrong kind of gap:
  - moving before: median speed of the last 5 reports >= 2 kn (a moored ship that goes quiet is normal);
  - well covered: the ship was heard at least every 3 min before AND after the gap, i.e. the
    receivers in that area reliably hear it (edge-of-coverage fade-outs report slowly);
  - not our own outage: gaps that overlap `outages` (epoch-second intervals from the recorder's
    own ledger, gaps-*.jsonl, and fleet-wide silences) are dropped. A dead recorder is not a
    dark ship. The caller supplies the intervals; without them nothing is excluded.
A track that simply ends is not a gap (we cannot tell leaving the area from going dark).
Tier 0 needs 30 min, tier 1-2 15 min.
"""

from __future__ import annotations

import numpy as np

from ._core import Grid, event, iso

MOVING_KN = 2.0
PAD_S = 120  # slack around each outage


def ais_gaps(g: Grid, tier: int, mmsi=None, outages=None) -> list[dict]:
    r = g.raw
    t = r["time"].to_numpy(float)
    if len(t) < 12:
        return []
    thr = (30 if tier == 0 else 15) * 60
    dt = np.diff(t)
    sog, lat, lon = r["sog"].to_numpy(float), r["lat"].to_numpy(float), r["lon"].to_numpy(float)
    out = []
    for i in np.flatnonzero(dt > thr):
        if i < 6 or i + 6 >= len(t):
            continue
        if np.nanmedian(sog[i - 4 : i + 1]) < MOVING_KN or np.isnan(sog[i - 4 : i + 1]).all():
            continue
        if np.median(dt[i - 8 : i]) > 180 or np.median(dt[i + 1 : i + 7]) > 180:
            continue
        t0, t1 = t[i], t[i + 1]
        if outages is not None and any(a - PAD_S < t1 and b + PAD_S > t0 for a, b in outages):
            continue
        km = float(np.hypot((lon[i + 1] - lon[i]) * np.cos(np.radians(lat[i])), lat[i + 1] - lat[i]) * 111.2)
        out.append(event(mmsi, "ais_gap", t0, t1, lat[i], lon[i],
                         {"rule": "gap_while_moving", "gap_min": float((t1 - t0) / 60),
                          "observed_kn": float(np.nanmedian(sog[i + 1 : i + 6])),
                          "reference_kn": float(np.nanmedian(sog[i - 4 : i + 1])),
                          "reappeared_km": km, "detected_at": iso(t1)}))
    return out
