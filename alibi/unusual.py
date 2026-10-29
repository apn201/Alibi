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
