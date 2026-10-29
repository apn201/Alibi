"""Own habit: is this ship usually this slow here?

This vessel's own earlier moving segments whose median position lies within RADIUS_KM of the
event, excluding the current journey (do not learn from what you flag). If the ship usually
passes here slower than its overall typical speed, that difference explains part of the drop.
Segments are moving-only (>= 2 kn) and located by their median position, so a habit of
stopping here is seen only partly; the numbers are in `details`.
"""

from __future__ import annotations

import numpy as np

from ..profiles import km_between
from ._util import SUPPORTS, deviation_kn, no_slowdown, share, unavailable, window_delta
from .base import Context, Finding

RADIUS_KM = 5.0
MIN_PASSAGES = 3
EXCLUDE_S = 6 * 3600  # the current journey, around the event


class OwnHabit:
    id = "own_habit"
    title = "Own habit: this ship at this place before"
    kind = "behaviour"
    attribution = "ALIBI profile DB (Danish Maritime Authority AIS, Fintraffic Digitraffic AIS)"
    lamp = "PLC"

    def evaluate(self, ctx: Context) -> Finding:
        pdata, cov = ctx.extra["profiles"], ctx.extra.get("coverage")
        if not pdata.segments_ok or cov is None:
            return unavailable(self.id, "This place and time are outside the AIS history ALIBI holds, "
                               "so this ship's habit here is unknown.", self.lamp, coverage=cov)
        mmsis = ctx.extra.get("mmsis") or []
        if not mmsis:
            return unavailable(self.id, "The ship could not be identified, so its habit here is unknown.", self.lamp)
        dev = deviation_kn(ctx)
        if dev is None or dev <= 0:
            return no_slowdown(self.id, self.lamp)
        s = pdata.seg
        idx = pdata.segments_of(mmsis)
        idx = idx[(s["t1"][idx] < ctx.event_start - EXCLUDE_S) | (s["t0"][idx] > ctx.event_end + EXCLUDE_S)]
        near = idx[km_between(ctx.lat, ctx.lon, s["lat"][idx], s["lon"][idx]) <= RADIUS_KM]
        own = ctx.extra.get("own_profile")
        typical = own["speed"] if own else (float(np.median(s["speed"][idx])) if len(idx) else None)
        det = {"passages_within_km": RADIUS_KM, "passages": int(len(near)), "segments_total": int(len(idx)),
               "typical_kn": None if typical is None else round(float(typical), 2)}
        if len(near) < MIN_PASSAGES or typical is None:
            return Finding(self.id, "neutral", f"This ship has fewer than {MIN_PASSAGES} earlier passages within "
                           f"{RADIUS_KM:.0f} km, so its habit here is not known.", lamp=self.lamp,
                           source_reference=f"profile_db segments ({cov})", details=det)
        here = float(np.median(s["speed"][near]))
        delta = max(0.0, typical - here)
        e = share(delta, ctx)
        det.update(here_median_kn=round(here, 2), slower_here_kn=round(delta, 2), explains=round(e, 3))
        ref = f"profile_db segments ({cov}), {len(near)} passages"
        if e >= SUPPORTS:
            return Finding(self.id, "supports_explanation",
                           f"This ship usually passes here at {here:.1f} kn, below its typical {typical:.1f} kn "
                           f"({len(near)} earlier passages within {RADIUS_KM:.0f} km).", e, 0.0, self.lamp,
                           source_reference=ref, details=det, expected_delta_kn=window_delta(ctx, delta))
        if ctx.observed_kn is not None and here > ctx.observed_kn + 0.5 * dev:
            return Finding(self.id, "weakens_explanation",
                           f"This ship has passed here {len(near)} times before at a median {here:.1f} kn; "
                           "it does not usually slow down here.", e, 0.0, self.lamp, source_reference=ref, details=det)
        return Finding(self.id, "neutral", f"This ship's earlier passages here ({len(near)}, median {here:.1f} kn) "
                       "neither explain nor contradict the drop.", e, 0.0, self.lamp, source_reference=ref,
                       details=det, expected_delta_kn=window_delta(ctx, delta) if delta > 0 else None)


EXPLAINER = OwnHabit()
