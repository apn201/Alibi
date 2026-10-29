"""Grounding pattern, from one confirmed case (TERRY, Oresund, 22 March 2012).

The template in the track: a ship leaves its anchorage and turns about for a while
(erratic course), settles on a straight run at 11-12 kn, then its speed falls from cruise
to under 1 kn within a few minutes and stays there. A ship that stops on purpose slows
over a longer stretch, so an abrupt stop from a steady run is the discriminating part.

Rule (per tier; tier 0 is the most conservative):
    straight run   median speed >= 8 kn (tier 0) or 6 kn, course spread <= 12 deg, for 10 min
    abrupt stop    speed < 1 kn within 6 min (5 at tier 0) of the end of the run
    stays          >= 80 % of the next 20 min below 1 kn, moved < 0.6 km
    erratic before turning rate >= 3 deg/min in the hour before the run (required at tier 0 only;
                   recorded as `erratic_before` otherwise)
"Outside a stop area": tiers 0 and 1 skip stops inside learnt stop areas (rules._core.learn_stop_areas:
grid cells where 3+ ships each sat still for 20+ min); tier 2 keeps them. Without that layer the
rule rests on the run alone: a ship arriving at a berth or anchorage does not come in at 6+ kn and
stop within minutes, but ferries berthing and the odd crash stop will still fire. Over-flagging on
purpose; it is what the second opinion is for.
The AIS navigation status is never used (a grounded ship may still say "under way").
"""

from __future__ import annotations

import numpy as np

from ._core import Grid, cell, circ_std, event, iso, to_xy

RUN_MIN = 10
STAY_MIN = 20


def grounding(g: Grid, tier: int, mmsi=None, stops=None) -> list[dict]:
    sog, cog = g.sog, g.cog
    n = len(sog)
    if n < RUN_MIN + STAY_MIN + 5 or np.nanmax(sog, initial=0) < 6:
        return []
    run_kn = 8.0 if tier == 0 else 6.0
    stop_min = 5 if tier == 0 else 6
    out, i, last_end = [], RUN_MIN, -10**9
    # candidate stop minute b: first minute below 1 kn after a minute at run speed
    slow = np.nan_to_num(sog, nan=99.0) < 1.0
    for b in np.flatnonzero(slow & ~np.r_[False, slow[:-1]]):
        if b < RUN_MIN + 1 or b + STAY_MIN > n or b < last_end:
            continue
        a_win = sog[max(b - stop_min - RUN_MIN, 0) : b - stop_min]  # the run, ending stop_min before the stop
        if len(a_win) < RUN_MIN or np.sum(~np.isnan(a_win)) < 7 or np.nanmedian(a_win) < run_kn:
            continue
        if circ_std(cog[b - stop_min - RUN_MIN : b - stop_min]) > 12:
            continue
        after = sog[b : b + STAY_MIN]
        ok = after[~np.isnan(after)]
        if len(ok) < 10 or np.mean(ok < 1.0) < 0.8:
            continue
        x, y = to_xy(g.lat[b : b + STAY_MIN], g.lon[b : b + STAY_MIN])
        if np.hypot(np.nanmax(x) - np.nanmin(x), np.nanmax(y) - np.nanmin(y)) > 0.6:
            continue
        if tier < 2 and stops is not None and cell(float(np.nanmedian(g.lat[b : b + STAY_MIN])),
                                                   float(np.nanmedian(g.lon[b : b + STAY_MIN]))) in stops:
            continue  # a berth or anchorage other ships use: arriving, not running aground
        before = cog[max(b - stop_min - RUN_MIN - 60, 0) : b - stop_min - RUN_MIN]
        d = np.abs((np.diff(before) + 180) % 360 - 180)
        turn = float(np.nanmean(d)) if np.sum(~np.isnan(d)) >= 5 else 0.0
        erratic = turn >= 3.0
        if tier == 0 and not erratic:
            continue
        lo = b - stop_min - RUN_MIN
        last_end = b + STAY_MIN
        out.append(event(mmsi, "grounding_pattern", g.time(lo), g.time(b + STAY_MIN),
                         float(np.nanmedian(g.lat[b : b + STAY_MIN])), float(np.nanmedian(g.lon[b : b + STAY_MIN])),
                         {"rule": "straight_run_then_abrupt_stop", "observed_kn": float(np.nanmedian(after)),
                          "reference_kn": float(np.nanmedian(a_win)), "stop_within_min": stop_min,
                          "erratic_before": bool(erratic), "turn_deg_per_min": turn, "detected_at": iso(g.time(b))}))
    return out
