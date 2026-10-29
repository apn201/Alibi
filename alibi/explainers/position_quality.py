"""Position quality: can the track be trusted? Moves confidence only, never Unusual or Unexplained.

Two checks over the submitted track:
    jumps      consecutive positions implying more than JUMP_KN (a GNSS or AIS artefact)
    sparse     median reporting interval over SPARSE_S, or a gap over GAP_S inside the event window
The accuracy and RAIM flags are reported in `details` only: most AIS transponders report
"low accuracy" (> 10 m), which says nothing about a speed change.
Poor quality lowers confidence; it never makes a ship look more suspicious.
"""

from __future__ import annotations

import numpy as np

from .base import Context, Finding

JUMP_KN = 50.0
SPARSE_S = 180
GAP_S = 900


class PositionQuality:
    id = "position_quality"
    title = "Position quality (accuracy flags, jumps, reporting gaps)"
    kind = "quality"
    attribution = "The submitted track"
    lamp = "GNSS"

    def evaluate(self, ctx: Context) -> Finding:
        tr = ctx.track
        t, lat, lon = tr["time"].to_numpy(float), tr["lat"].to_numpy(float), tr["lon"].to_numpy(float)
        dt = np.diff(t)
        dist_nm = np.hypot(np.diff(lat) * 110.57,
                           np.diff(lon) * 111.32 * np.cos(np.radians(lat[:-1]))) / 1.852
        ok = dt > 0
        implied = np.where(ok, dist_nm / np.where(ok, dt, 1) * 3600, 0.0)
        jumps = int((implied > JUMP_KN).sum())
        ev = (t >= ctx.event_start) & (t <= ctx.event_end)
        tev = t[ev]
        gap_ev = float(np.diff(tev).max()) if len(tev) >= 2 else float(ctx.event_end - ctx.event_start)
        median_dt = float(np.median(dt)) if len(dt) else 0.0
        acc = tr["pos_acc"].to_numpy(float)
        acc_known = np.isfinite(acc)
        low_acc = float((acc[acc_known] == 0).mean()) if acc_known.any() else None
        raim = tr["raim"].to_numpy(float)
        raim_share = float((raim[np.isfinite(raim)] == 1).mean()) if np.isfinite(raim).any() else None
        det = {"position_jumps": jumps, "median_interval_s": round(median_dt, 1), "max_gap_in_event_s": round(gap_ev),
               "low_accuracy_share": None if low_acc is None else round(low_acc, 3),
               "raim_in_use_share": None if raim_share is None else round(raim_share, 3)}
        issues, penalty = [], 0.0
        if jumps:
            issues.append(f"{jumps} position jump(s) implying more than {JUMP_KN:.0f} kn")
            penalty += 0.3
        if median_dt > SPARSE_S or gap_ev > GAP_S:
            issues.append("sparse reporting")
            penalty += 0.2
        if not issues:
            return Finding(self.id, "neutral", "The track reports regularly and shows no position jumps.",
                           lamp=self.lamp, source_reference="submitted track", details=det)
        return Finding(self.id, "neutral", "The track has quality problems (" + "; ".join(issues) + "), which "
                       "lowers confidence.", 0.0, min(penalty, 0.5), self.lamp, source_reference="submitted track",
                       details={**det, "issues": issues})


EXPLAINER = PositionQuality()
