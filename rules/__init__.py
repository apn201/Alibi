"""Detector rules, shared by the demo AIS tool (detector/) and ALIBI's track mode.

Stateless: every rule looks at one ship's track and nothing else, the way an ordinary
upstream AIS system would. Deliberately sensitive; ALIBI is what makes that affordable.

Contract (implemented in this package):

    detect(track: pandas.DataFrame, sensitivity: float = 0.5) -> list[dict]

`track` has columns time (epoch s UTC), lat, lon, sog, cog, heading (NaN where missing),
sorted by time, one ship. Returns CandidateEvent dicts as in alibi-openapi.yaml:
    {"event_id", "event_type", "start_time", "end_time" (ISO UTC, "Z"),
     "location": {"latitude", "longitude"}, "baseline_summary": {"rule", "observed_kn", "reference_kn", ...}}
event_type is one of: slowdown, grounding_pattern, ais_gap, corridor_loiter.

Extras beyond the contract (all optional keywords): `mmsi` (also read from a `mmsi` column or
`track.attrs["mmsi"]`; goes into the event ids and `vessel_id`), `outages` (list of
(start, end) epoch-second recorder outages; ais_gap events overlapping them are dropped), `stops` (a set of
grid cells from `learn_stop_areas`: berths and anchorages, so tiers 0-1 do not report arrivals).

Sensitivity s in [0, 1] maps to three tiers, see `tier()`:
    tier 0 (s < 0.4)   conservative: slowdown below 0.7 x only; longer thresholds elsewhere
    tier 1 (s < 0.8)   adds the 4-sigma and 10 % rule, shorter gap/corridor thresholds
    tier 2 (s >= 0.8)  also 5-minute windows
Every event gets baseline_summary["min_tier"] only via `detect_tiers`, which the demo detector
uses to store one superset per case and filter by sensitivity at replay time.
"""

from __future__ import annotations

import pandas as pd

from ._core import Grid, learn_stop_areas, merge, prepare
from .corridor import corridor_loiter, corridors
from .gaps import ais_gaps
from .grounding import grounding
from .slowdown import slowdown

__all__ = ["detect", "detect_tiers", "tier", "corridors", "learn_stop_areas"]


def tier(sensitivity: float) -> int:
    return 0 if sensitivity < 0.4 else 1 if sensitivity < 0.8 else 2


def _mmsi(track: pd.DataFrame, mmsi):
    if mmsi is not None:
        return int(mmsi)
    if "mmsi" in track.columns and track["mmsi"].notna().any():
        return int(track["mmsi"].dropna().iloc[0])
    return track.attrs.get("mmsi")


def _run(g: Grid, t: int, mmsi, outages, stops) -> list[dict]:
    ev = slowdown(g, t, mmsi, stops) + grounding(g, t, mmsi, stops) + ais_gaps(g, t, mmsi, outages) + corridor_loiter(g, t, mmsi, stops)
    return merge(ev)


def detect(track: pd.DataFrame, sensitivity: float = 0.5, mmsi=None, outages=None, stops=None) -> list[dict]:
    g = prepare(track)
    return [] if g is None else _run(g, tier(sensitivity), _mmsi(track, mmsi), outages, stops)


def detect_tiers(track: pd.DataFrame, mmsi=None, outages=None, stops=None) -> list[dict]:
    """Events of the most sensitive tier, each tagged with baseline_summary["min_tier"]: the lowest
    tier at which an event of the same type overlapping it also fires. One call, three runs."""
    g = prepare(track)
    if g is None:
        return []
    m = _mmsi(track, mmsi)
    by_tier = [_run(g, t, m, outages, stops) for t in (0, 1, 2)]
    out = by_tier[2]
    for e in out:
        e["baseline_summary"]["min_tier"] = next(
            (t for t in (0, 1) if any(o["event_type"] == e["event_type"] and o["start_time"] <= e["end_time"]
                                      and o["end_time"] >= e["start_time"] for o in by_tier[t])), 2)
    return out
