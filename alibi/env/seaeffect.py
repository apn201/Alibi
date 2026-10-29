"""Expected speed effect of the sea on a merchant ship: how many knots slower or faster than in flat water.

Why: the sea-state explainer must say how much of an observed slowdown the weather accounts for. Two parts,
both deliberately simple and documented, so a reviewer can check them.

(a) Current. Speed over ground changes by the current component along the course over ground:
    dSOG = (u*sin(COG) + v*cos(COG)) * 1.944 kn per m/s.   Positive = the current helps.

(b) Wind and waves, involuntary speed loss by Kwon's method (Y. J. Kwon, "Speed loss due to added resistance in
    wind and waves", The Naval Architect, March 2008, 14-16; basis Townsin and Kwon 1983, "Approximate formulae
    for the speed loss due to added resistance in wind and waves", RINA Trans. 125):
        dV/V [%] = C_beta * C_U * C_Form
    - Beaufort number BN from the 10 m wind: V = 0.836 * BN**1.5 m/s, so BN = (V/0.836)**(2/3).
    - C_beta, direction reduction coefficient by relative heading of the weather (0 = head sea): head 0-30 deg: 2.0;
      bow 30-60: 1.7 - 0.03 (BN-4)^2; beam 60-150: 0.9 - 0.06 (BN-6)^2; following 150-180: 0.4 - 0.03 (BN-8)^2
      (floored at 0).
    - C_Form, ship form coefficient for cargo/tanker: 0.5 BN + BN^6.5 / (2.7 * disp^(2/3)), disp = displacement in
      m^3, estimated from length as Cb*L*B*T with B = L/6.5, T = B/2.6 (Cb 0.75, laden).
    - C_U, speed coefficient by Froude number Fn = V/sqrt(g L) for Cb 0.75. Kwon tabulates it by Cb and Fn; here it is
      a linear fit 0.09*(1 - 2*(Fn - 0.15)), floored at 0.03. This is an approximation of the table, so absolute
      losses are indicative (a 150 m ship at 12 kn loses about 10 % head-on at BN 6, about 1 % following), and the
      loss is capped at 50 %. The explainer uses differences between two moments, which cancel part of the error.
    Waves are not an input of Kwon's method (BN stands for the whole weather). Hs is reported as a cross-check.

Not a ship-specific prediction: no loading condition, trim, hull fouling or engine limit. It is the sea's expected
push on a typical merchant ship, to be compared with what the ship actually did.
"""
from __future__ import annotations

import numpy as np

KN_PER_MS = 1.943844
G = 9.81
DEFAULT_LENGTH_M = {"S": 80.0, "M": 120.0, "L": 170.0, "XL": 280.0}
GROUP_LENGTH_M = {"tanker": 170.0, "cargo": 140.0, "passenger": 150.0}
MAX_LOSS_FRAC = 0.5


def default_length(cls: str | None, length: float | None = None) -> float:
    """Ship length: given, else from the class string ('cargo/L'), else 140 m."""
    if length and length > 20:
        return float(length)
    if cls:
        group, _, size = cls.partition("/")
        if size in DEFAULT_LENGTH_M:
            return DEFAULT_LENGTH_M[size]
        if group in GROUP_LENGTH_M:
            return GROUP_LENGTH_M[group]
    return 140.0


def beaufort(wind_ms):
    return (np.asarray(wind_ms, dtype="float64") / 0.836) ** (2.0 / 3.0)


def relative_angle(from_deg, heading_deg):
    """Angle between where the weather comes from and the ship's heading, 0 = from ahead, 180 = from astern."""
    return np.abs((np.asarray(from_deg, dtype="float64") - np.asarray(heading_deg, dtype="float64") + 180.0) % 360.0 - 180.0)


def c_beta(rel_deg, bn):
    rel, bn = np.broadcast_arrays(np.asarray(rel_deg, dtype="float64"), np.asarray(bn, dtype="float64"))
    head = np.full(rel.shape, 2.0)
    bow = 1.7 - 0.03 * (bn - 4) ** 2
    beam = 0.9 - 0.06 * (bn - 6) ** 2
    follow = 0.4 - 0.03 * (bn - 8) ** 2
    c = np.where(rel < 30, head, np.where(rel < 60, bow, np.where(rel < 150, beam, follow)))
    return np.maximum(c, 0.0)


def speed_loss_frac(wind_ms, wind_from_deg, heading_deg, speed_kn, length_m):
    """Kwon's dV/V as a fraction (0..0.5), and the components."""
    bn = beaufort(wind_ms)
    beam_m = length_m / 6.5
    disp = 0.75 * length_m * beam_m * (beam_m / 2.6)
    v = np.maximum(np.asarray(speed_kn, dtype="float64"), 0.0) / KN_PER_MS
    fn = v / np.sqrt(G * length_m)
    rel = relative_angle(wind_from_deg, heading_deg)
    cb = c_beta(rel, bn)
    cu = np.maximum(0.09 * (1 - 2 * (fn - 0.15)), 0.03)
    cf = 0.5 * bn + bn ** 6.5 / (2.7 * disp ** (2.0 / 3.0))
    frac = np.minimum(cb * cu * cf / 100.0, MAX_LOSS_FRAC)
    return frac, {"beaufort": bn, "rel_wind_deg": rel, "c_beta": cb, "c_u": cu, "c_form": cf, "froude": fn}


def current_along_course(cur_u, cur_v, cog_deg):
    """Current component along the course, in knots (positive = helps)."""
    a = np.radians(np.asarray(cog_deg, dtype="float64"))
    return (np.asarray(cur_u, dtype="float64") * np.sin(a) + np.asarray(cur_v, dtype="float64") * np.cos(a)) * KN_PER_MS


def expected_effect(wind_u=None, wind_v=None, cur_u=None, cur_v=None, hs_m=None, *, cog_deg, speed_kn, length_m=140.0):
    """Expected change of speed over ground caused by the sea, in knots (negative = slower). Arrays or scalars.

    Missing (NaN/None) inputs count as no effect for that part. Returns dict with delta_kn (total), current_kn,
    wind_loss_kn, wind_loss_pct, hs_m and the Kwon components.
    """
    def arr(x):
        return np.nan if x is None else np.asarray(x, dtype="float64")
    wu, wv, cu_, cv, hs = arr(wind_u), arr(wind_v), arr(cur_u), arr(cur_v), arr(hs_m)
    speed = np.asarray(speed_kn, dtype="float64")
    wspd = np.hypot(wu, wv)
    wfrom = np.degrees(np.arctan2(-wu, -wv)) % 360
    frac, comp = speed_loss_frac(wspd, wfrom, cog_deg, speed, length_m)
    loss_kn = np.nan_to_num(frac * speed)
    cur_kn = np.nan_to_num(current_along_course(cu_, cv, cog_deg))
    out = {"delta_kn": cur_kn - loss_kn, "current_kn": cur_kn, "wind_loss_kn": loss_kn,
           "wind_loss_pct": np.nan_to_num(frac * 100), "wind_speed_ms": wspd, "hs_m": hs}
    out.update(comp)
    return out
