"""Unusual: ALIBI's own second opinion on how far the ship is from what it should be doing.

Expected speed is the blend of lab 02-03 (`alibi_lab.profiles`): class prototype, the ship's
own profile and this journey (the pre-event part of the track), each weighted by its hours
of evidence:

    w_proto = K_PROTO, w_own = min(h_own, CAP_OWN), w_journey = min(h_journey * GAIN[tier], CAP[tier])

The drop over the event window is measured two ways and averaged:
    z    (expected - observed) / sigma, sigma = the ship's own steadiness (window-to-window
         spread on this journey; else its profile's within-segment IQR), at least 0.3 kn.
         U_z = 1 - exp(-max(0, z - 1) / 3): one sigma is noise, four sigmas is ~0.6.
    d    relative drop (expected - observed) / expected; U_d = min(1, d / 0.5): half speed is full.
    U = (U_z + U_d) / 2
A steady ship losing 10 % scores on z; an erratic ship halving its speed scores on d. Only
slowdowns count: a ship faster than expected is not unusual by this measure.

Other event types get their own measure (`measure` in the result), because a speed drop is
not what makes them unusual:
    gap        ais_gap. U_g = (1 - exp(-max(0, r - 3) / 10)) x min(1, gap_min / 30), r = gap over
               the ship's own median reporting interval in this track (a ship heard every 10 s
               that goes quiet for 20 min). U_m from where it reappeared: m = |ln(reappeared_km /
               expected_km)|, expected_km = pre-gap speed x gap time; U_m = 1 - exp(-max(0, m - 0.2) / 0.5)
               (moved further, or much less far, than its speed explains). U = 1 - (1 - U_g)(1 - U_m).
    loiter     corridor_loiter. U = (1 - exp(-slow_min / 30)) x (0.5 + 0.5 x (1 - s)), slow_min =
               minutes under 4 kn in the event window, s = share of this tile's segments under 5 kn
               for the ship's type group (where ships often stop, stopping is less unusual).
    grounding  grounding_pattern. The fingerprint (steady run, abrupt stop) is strong by itself:
               U = 0.6 + 0.4 x exp(-stop_min / 10), at least the speed measure.
    speed      slowdown and everything else: the speed measure above.
Explainers that bear on the measure explain shares of it (alibi.assess.APPLIES); X <= U holds
for every measure because X = U x prod(1 - e) with each e in [0, 1].
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from alibi_lab.profiles import CAP_JOURNEY, CAP_OWN, FREQUENT_HOURS, JOURNEY_GAIN, K_PROTO, MOVING_KN, SCALE_FLOOR_KN

from .profiles import WORKING_GROUPS, ProfileData

WINDOW_S = 600
IQR_TO_SIGMA = 1 / 1.349


def journey(pre: pd.DataFrame) -> tuple[float | None, float, list[float]]:
    """(median moving speed, moving hours, 10-minute window medians) of the pre-event track."""
    mv = pre[pre["sog"] >= MOVING_KN]
    if len(mv) < 5:
        return None, 0.0, []
    dt = np.diff(mv["time"].to_numpy(float))
    hours = float(np.clip(dt, 0, 300).sum() / 3600)
    w = (mv["time"] // WINDOW_S).to_numpy()
    meds = [float(g.median()) for _, g in mv["sog"].groupby(w) if len(g) >= 3]
    return float(mv["sog"].median()), hours, meds


def expected(pdata: ProfileData, vessel: dict, pre: pd.DataFrame) -> dict:
    proto = pdata.class_profile(vessel.get("cls") or "unknown/?") if pdata.ok else None
    own = pdata.vessels.get(vessel.get("vessel_key")) if pdata.ok else None
    if own is not None and not (own["speed"] == own["speed"]):
        own = None
    tier = "new" if own is None else ("frequent" if own["hours"] >= FREQUENT_HOURS else "rare")
    j_speed, j_hours, meds = journey(pre)
    parts = []
    if proto is not None:
        parts.append(("prototype", proto["speed"], K_PROTO))
    if own is not None:
        parts.append(("own", own["speed"], min(own["hours"], CAP_OWN)))
    if j_speed is not None and j_hours > 0:
        parts.append(("journey", j_speed, min(j_hours * JOURNEY_GAIN[tier], CAP_JOURNEY[tier])))
    if not parts:
        return {"expected_kn": None, "weights": {}, "tier": "prototype", "sigma_kn": SCALE_FLOOR_KN}
    v = np.array([p[1] for p in parts], dtype=float)
    w = np.array([p[2] for p in parts], dtype=float)
    exp_kn = float((v * w).sum() / w.sum())
    if len(meds) >= 3:
        m = np.asarray(meds)
        sigma, sigma_from = 1.4826 * float(np.median(np.abs(m - np.median(m)))), "journey"
    elif own is not None and own["speed_iqr"] == own["speed_iqr"]:
        sigma, sigma_from = own["speed_iqr"] * IQR_TO_SIGMA, "own_profile"
    else:
        sigma, sigma_from = (proto["speed_iqr"] if proto else 1.0) * IQR_TO_SIGMA, "class_profile"
    label = max(parts, key=lambda p: p[2])[0]
    if vessel.get("group") in WORKING_GROUPS:
        label = "working"
    return {"expected_kn": exp_kn, "tier": label, "history_tier": tier,
            "weights": {p[0]: round(p[2], 3) for p in parts}, "components_kn": {p[0]: round(p[1], 2) for p in parts},
            "sigma_kn": max(sigma, SCALE_FLOOR_KN), "sigma_from": sigma_from, "journey_hours": round(j_hours, 2),
            "class_speed_kn": proto["speed"] if proto else None, "own": own}


def unusual(expected_kn: float | None, observed_kn: float | None, sigma_kn: float) -> dict:
    if expected_kn is None or observed_kn is None or expected_kn <= 0:
        return {"unusual": None}
    drop = expected_kn - observed_kn
    z = drop / sigma_kn
    d = drop / expected_kn
    u_z = 1 - math.exp(-max(0.0, z - 1) / 3)
    u_d = min(1.0, max(0.0, d) / 0.5)
    return {"unusual": round((u_z + u_d) / 2, 4), "z": round(z, 2), "relative_drop": round(d, 3),
            "u_z": round(u_z, 4), "u_d": round(u_d, 4)}


SLOW_KN = 4.0


def _ts(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def measure_for(event_type: str | None) -> str:
    return {"ais_gap": "gap", "corridor_loiter": "loiter", "grounding_pattern": "grounding"}.get(event_type or "", "speed")


def gap(track: pd.DataFrame, start: int, end: int, summary: dict) -> dict:
    t = track["time"].to_numpy(float)
    dt = np.diff(t)
    if not len(dt):
        return {"unusual": None}
    inside = (t[1:] > start) & (t[:-1] < end)
    gap_s = float(dt[inside].max()) if inside.any() else float(end - start)
    i = int(np.flatnonzero(inside)[np.argmax(dt[inside])]) if inside.any() else None
    usual_dt = float(np.median(dt[~inside])) if (~inside).sum() >= 3 else float(np.median(dt))
    r = gap_s / max(usual_dt, 10.0)
    u_g = (1 - math.exp(-max(0.0, r - 3) / 10)) * min(1.0, gap_s / 60 / 30)
    km = _ts(summary.get("reappeared_km"))
    ref_kn = _ts(summary.get("reference_kn"))
    if i is not None:
        lat, lon = track["lat"].to_numpy(float), track["lon"].to_numpy(float)
        if km is None:
            km = float(np.hypot((lat[i + 1] - lat[i]) * 110.57, (lon[i + 1] - lon[i]) * 111.32 * math.cos(math.radians(lat[i]))))
        if ref_kn is None:
            before = track["sog"].to_numpy(float)[max(0, i - 4): i + 1]
            ref_kn = float(np.nanmedian(before)) if np.isfinite(before).any() else None
    u_m, m, exp_km = 0.0, None, None
    if km is not None and ref_kn is not None and ref_kn > 0:
        exp_km = ref_kn * 1.852 * gap_s / 3600
        m = abs(math.log(max(km, 0.05) / max(exp_km, 0.05)))
        u_m = 1 - math.exp(-max(0.0, m - 0.2) / 0.5)
    u = 1 - (1 - u_g) * (1 - u_m)
    return {"unusual": round(u, 4), "measure": "gap", "gap_min": round(gap_s / 60, 1),
            "usual_interval_s": round(usual_dt, 1), "gap_ratio": round(r, 1), "u_gap": round(u_g, 4),
            "reappeared_km": None if km is None else round(km, 2), "expected_km": None if exp_km is None else round(exp_km, 2),
            "displacement_mismatch": None if m is None else round(m, 3), "u_moved": round(u_m, 4)}


def loiter(ev: pd.DataFrame, start: int, end: int, tile: dict | None) -> dict:
    sog = ev["sog"].to_numpy(float)
    ok = np.isfinite(sog)
    slow_min = (end - start) / 60 * float((sog[ok] < SLOW_KN).mean()) if ok.any() else 0.0
    s = tile["slow_share"] if tile and tile.get("segments", 0) >= 5 else 0.0
    u = (1 - math.exp(-slow_min / 30)) * (0.5 + 0.5 * (1 - s))
    return {"unusual": round(u, 4), "measure": "loiter", "slow_min": round(slow_min, 1), "tile_slow_share": round(s, 3)}


def grounding(track: pd.DataFrame, start: int, summary: dict, speed_u: float | None) -> dict:
    stop_min = _ts(summary.get("stop_within_min"))
    if stop_min is None:  # time from the last report at >= 70 % of cruise to the first under 1 kn
        t, sog = track["time"].to_numpy(float), track["sog"].to_numpy(float)
        ref = _ts(summary.get("reference_kn")) or (float(np.nanmedian(sog[t < start])) if (t < start).any() else None)
        stopped = np.flatnonzero((t >= start - 1800) & (sog < 1.0))
        if ref and len(stopped):
            ts = t[stopped[0]]
            run = np.flatnonzero((t < ts) & (sog >= 0.7 * ref))
            stop_min = (ts - t[run[-1]]) / 60 if len(run) else None
    u = 0.6 + 0.4 * math.exp(-stop_min / 10) if stop_min is not None else 0.8
    u = max(u, speed_u or 0.0)
    return {"unusual": round(u, 4), "measure": "grounding", "stop_within_min": None if stop_min is None else round(stop_min, 1)}
