"""Fleet: did the ships around slow down too?

Other ships' moving segments within RADIUS_KM of the event and overlapping the event window
widened by WINDOW_S, each compared with that ship's own profile speed. If the fleet as a
whole ran below its usual speed, that shared slowdown explains the same share of this ship's
drop (something slowed everybody; sea_state may say what). A fleet that kept its speed while
this ship slowed weakens the explanation. Needs MIN_SHIPS other ships, else neutral.
Segments longer than MAX_SEG_S are skipped: their median says little about one hour.
"""

from __future__ import annotations

import numpy as np

from ..profiles import km_between
from ._util import SUPPORTS, deviation_kn, no_slowdown, share, unavailable, window_delta
from .base import Context, Finding

RADIUS_KM = 25.0
WINDOW_S = 90 * 60
MIN_SHIPS = 5
MAX_SEG_S = 8 * 3600
MIN_OWN_KN = 3.0  # ships whose usual speed is lower than this do not cruise; left out


class Fleet:
    id = "fleet"
    title = "Fleet: other ships nearby at the same time"
    kind = "behaviour"
    attribution = "ALIBI profile DB (Danish Maritime Authority AIS, Fintraffic Digitraffic AIS)"
    lamp = "TRF"

    def evaluate(self, ctx: Context) -> Finding:
        pdata, cov = ctx.extra["profiles"], ctx.extra.get("coverage")
        if not pdata.segments_ok or cov is None:
            return unavailable(self.id, "This place and time are outside the AIS history ALIBI holds, "
                               "so the traffic around the ship is unknown.", self.lamp, coverage=cov)
        dev = deviation_kn(ctx)
        if dev is None or dev <= 0:
            return no_slowdown(self.id, self.lamp)
        s = pdata.seg
        idx = pdata.segments_window(ctx.event_start - WINDOW_S, ctx.event_end + WINDOW_S)
        idx = idx[(s["t1"][idx] - s["t0"][idx] <= MAX_SEG_S) & ~np.isin(s["mmsi"][idx], ctx.extra.get("mmsis") or [])]
        idx = idx[km_between(ctx.lat, ctx.lon, s["lat"][idx], s["lon"][idx]) <= RADIUS_KM]
        own = s["own_speed"][idx]
        idx = idx[np.isfinite(own) & (own >= MIN_OWN_KN)]
        rel = s["speed"][idx] / s["own_speed"][idx]
        # one value per ship: its median relative speed over its segments in the window
        mm = s["mmsi"][idx]
        ships = np.unique(mm)
        per_ship = np.array([np.median(rel[mm == m]) for m in ships]) if len(ships) else np.array([])
        det = {"radius_km": RADIUS_KM, "window_min": WINDOW_S // 60, "ships": int(len(ships)), "coverage": cov}
        ref = f"profile_db segments ({cov}), {len(ships)} ships"
        if len(ships) < MIN_SHIPS:
            return Finding(self.id, "neutral", f"Fewer than {MIN_SHIPS} other ships were within {RADIUS_KM:.0f} km "
                           "at the time, too few to judge the traffic.", lamp=self.lamp, source_reference=ref,
                           details=det, confidence_penalty=0.05)
        fleet_rel = float(np.median(per_ship))
        slower = int((per_ship < 0.85).sum())
        delta = max(0.0, 1.0 - fleet_rel) * ctx.expected_kn
        e = share(delta, ctx)
        det.update(fleet_relative_speed=round(fleet_rel, 3), ships_slower_15pct=slower, explains=round(e, 3))
        pct = (1 - fleet_rel) * 100
        if e >= SUPPORTS:
            return Finding(self.id, "supports_explanation", f"The {len(ships)} other ships within {RADIUS_KM:.0f} km "
                           f"were also running {pct:.0f} % below their usual speed at the time.", e, 0.0, self.lamp,
                           source_reference=ref, details=det, expected_delta_kn=window_delta(ctx, delta))
        if fleet_rel >= 0.95:
            return Finding(self.id, "weakens_explanation", f"The {len(ships)} other ships within {RADIUS_KM:.0f} km "
                           "kept their usual speed at the time.", e, 0.0, self.lamp, source_reference=ref, details=det)
        return Finding(self.id, "neutral", f"The {len(ships)} other ships within {RADIUS_KM:.0f} km were slightly "
                       "slower than usual, which explains little of the drop.", e, 0.0, self.lamp,
                       source_reference=ref, details=det,
                       expected_delta_kn=window_delta(ctx, delta) if delta > 0 else None)


EXPLAINER = Fleet()
