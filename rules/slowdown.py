"""Slowdown against the ship's own journey, and the Eagle S fingerprint.

Why this rule, and why it needs no profile: an upstream AIS system usually knows nothing
about a ship's habits, but it can always compare a ship with itself a little earlier.
The reference is the median speed of the previous hour (ending one window before the one
judged), so it needs only the track. Only ships that were cruising (reference >= 6 kn) and
steady (spread of their own 10-min medians <= 12 % of the reference) for at least 30 min
are judged: for anyone else "slower than before" is ordinary manoeuvring.

Rule pair from lab 03 (alibi_lab/profiles.py, JourneyTracker.too_slow):
    A  window median < 0.7 x reference                      (always)
    B  window median < reference - 4 sigma  AND  < 0.9 x reference   (sensitivity tier >= 1)
sigma = robust spread of the ship's own window medians, at least 0.3 kn. Tier 2 also judges
5-minute windows instead of 10-minute ones.

Once a change starts, its reference stays frozen at the value from before it, so a lasting
slowdown cannot teach itself to look normal (the "do not learn from what you flag" rule). Changes
are tracked with the most sensitive rule for every tier; the tier only decides which ones are
reported, and when. The event ends when the speed is back above the thresholds for 3 minutes.

Fingerprint "steady_cruise_drop" (Eagle S, 25 Dec 2024): an hour or more of very steady
cruise (spread <= 6 %), then a sustained drop of 15-35 % while the course is held (circular
spread <= 10 degrees and within 15 degrees of the course before). It is an annotation on a
slowdown event, not a separate trigger, so it never fires where the general rule is silent.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ._core import Grid, ang_diff, cell, circ_mean, circ_std, event, iso

REF_MIN = 60  # reference window, minutes
CRUISE_KN = 6.0
STEADY = 0.12  # of the reference
FP_STEADY = 0.06
SIGMA_FLOOR = 0.3
MAX_EVENT_MIN = 180


def _series(g: Grid, w: int):
    s = pd.Series(g.sog)
    obs = s.rolling(w, min_periods=max(3, w // 2)).median()
    past = s.shift(w)
    ref = past.rolling(REF_MIN, min_periods=30).median()
    prev = obs.shift(w)
    sigma = (prev.rolling(REF_MIN, min_periods=20).quantile(0.75) - prev.rolling(REF_MIN, min_periods=20).quantile(0.25)) / 1.349
    n_valid = past.rolling(REF_MIN, min_periods=1).count()
    cruising = (past >= 0.7 * ref).rolling(REF_MIN, min_periods=1).sum()
    ok = (ref >= CRUISE_KN) & (n_valid >= 30) & (cruising >= 0.8 * n_valid) & (sigma <= STEADY * ref)
    return obs.to_numpy(), ref.to_numpy(), sigma.to_numpy(), ok.to_numpy()


def _breach(obs, ref, sig, tier):
    """Rule A (and B from tier 1) against a fixed reference. NaN compares False."""
    with np.errstate(invalid="ignore"):
        a = obs < 0.7 * ref
        return a | ((obs < ref - 4 * sig) & (obs < 0.9 * ref)) if tier >= 1 else a


def slowdown(g: Grid, tier: int, mmsi=None, stops=None) -> list[dict]:
    """Find every change of speed (the most sensitive rule, 5-min windows, freezes the reference),
    then report the ones the chosen tier's own rule also catches. Tracking changes at the
    sensitive level for all tiers is what keeps a slow, stepwise decline from teaching the
    reference to follow it down, even when the tier itself is the conservative 0.7 x rule.

    A change that ends with the ship stopped (5-min median < 1 kn) is how every arrival looks. The event
    ends at the stop and is marked `ends_stopped`. Tier 0 drops those that reach the stop within an hour
    of the onset; tier 1 drops those that stop in a learnt stop area (`stops`); tier 2 keeps them."""
    if np.nanmax(g.sog, initial=0) < CRUISE_KN:
        return []
    obs5, ref, sigma, ok = _series(g, 5)
    sig = np.maximum(sigma, SIGMA_FLOOR)
    w = 5 if tier >= 2 else 10
    obs_t = pd.Series(g.sog).rolling(w, min_periods=max(3, w // 2)).median().to_numpy()
    out, cursor = [], 0
    for i0 in np.flatnonzero(ok & _breach(obs5, ref, sig, 1)):
        if i0 < cursor:
            continue
        ref0, sig0, sraw = ref[i0], sig[i0], sigma[i0]
        change = _breach(obs5[i0:], ref0, sig0, 1)
        back = pd.Series(~change & ~np.isnan(obs5[i0:])).rolling(3).sum().to_numpy() == 3
        stop = int(np.argmax(back)) if back.any() else len(back)
        i1 = i0 + max(stop - 3, 0)  # last minute still changed
        i1 = min(i1, i0 + MAX_EVENT_MIN)  # after 3 h a lasting change is the ship's new normal, not an event
        cursor = i0 + stop + 1
        # the chosen tier's rule, against the same frozen reference, must hold for 2 minutes in a row (1 at tier 2)
        stopped = np.flatnonzero(obs5[i0 : i1 + 1] < 1.0)
        k = i0 + int(stopped[0]) if len(stopped) else None
        if k is not None:
            i1 = k
            at_stop = stops is not None and cell(g.lat[k], g.lon[k]) in stops if not np.isnan(g.lat[k]) else False
            if (tier == 0 and k - i0 <= 60) or (tier == 1 and at_stop):
                continue
        rep = _breach(obs_t[max(i0 - 5, 0) : i1 + 1], ref0, sig0, tier)
        need = 1 if tier >= 2 else 2
        hit = np.flatnonzero(pd.Series(rep).rolling(need).sum().to_numpy() == need)
        if len(hit) == 0:
            continue
        j = max(i0 - 5, 0) + int(hit[0]) - (need - 1)
        lo, hi = max(i0 - 4, 0), i1
        observed = float(np.nanmedian(g.sog[lo : hi + 1]))
        a_rule = bool(np.any(obs_t[j : j + 1] < 0.7 * ref0))
        summary = {"rule": "ratio_0.7" if a_rule else "sigma_4_and_10pct", "observed_kn": observed,
                   "reference_kn": float(ref0), "drop_pct": round(100 * (1 - observed / ref0), 1),
                   "sigma_kn": float(sig0), "window_min": w, "detected_at": iso(g.time(j) + 60)}
        if k is not None:
            summary["ends_stopped"] = True
        if _fingerprint(g, lo, hi, ref0, sraw):
            summary["fingerprint"] = "steady_cruise_drop"
        out.append(event(mmsi, "slowdown", g.time(lo), g.time(hi) + 60, float(np.nanmedian(g.lat[lo : hi + 1])),
                         float(np.nanmedian(g.lon[lo : hi + 1])), summary))
    return out


def _fingerprint(g: Grid, lo: int, hi: int, ref0: float, sigma_raw: float) -> bool:
    """Long steady cruise, then a sustained 15-35 % drop with the course held."""
    if not (sigma_raw <= FP_STEADY * ref0) or hi - lo < 12:
        return False
    observed = float(np.nanmedian(g.sog[lo : lo + 15]))
    if not (0.65 * ref0 <= observed <= 0.85 * ref0):
        return False
    before = g.cog[max(lo - 60, 0) : lo]
    during = g.cog[lo + 5 : min(hi + 1, lo + 20)]
    if np.isnan(before).all() or np.isnan(during).all():
        return False
    return circ_std(during) <= 10 and ang_diff(circ_mean(during), circ_mean(before)) <= 15
