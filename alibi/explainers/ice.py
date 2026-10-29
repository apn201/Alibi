"""Ice explainer (lamp ICE): does sea ice at the ship's position account for the slowdown?

Why: in a Baltic winter a ship in drift or brash ice slows for reasons the AIS track cannot show. The Copernicus
Baltic physics product gives sea-ice concentration (siconc, 0..1) and thickness (sithick, m) hourly.

Model, deliberately simple and stated as an assumption: below 30 % concentration ice does not slow a ship. From 30 %
the expected speed loss is 20 % of the open-water speed, rising linearly to 80 % at full cover:
loss(c) = 0.2 + 0.6 * (c - 0.3) / 0.7 for c >= 0.3. Thickness is reported but not used. The predicted drop is
loss(event) - loss(baseline) times the baseline speed; explains = clip(predicted / observed drop, 0, 1).
"""
from __future__ import annotations

import numpy as np

from alibi.explainers.base import Context, Finding
from alibi.explainers.sea_state import MIN_DROP_FRAC, MIN_DROP_KN, _med, _r, env_along_track

ICE_MIN = 0.3
ATTRIBUTION = ("Generated using E.U. Copernicus Marine Service Information: Baltic Sea Physics Analysis and Forecast "
               "(BALTICSEA_ANALYSISFORECAST_PHY_003_006).")


def loss_fraction(c: float | None) -> float:
    if c is None or not np.isfinite(c) or c < ICE_MIN:
        return 0.0
    return 0.2 + 0.6 * (min(c, 1.0) - ICE_MIN) / (1 - ICE_MIN)


class Ice:
    id = "ice"
    title = "Sea ice"
    kind = "behaviour"
    attribution = ATTRIBUTION

    def evaluate(self, ctx: Context) -> Finding:
        got = env_along_track(ctx)
        if got is not None:
            tr, env, ev, pre = got
            have = (env.attrs["sources_per_row"]["phy"] != None).any()  # noqa: E711
        if got is None or not have or not ev.any():
            return Finding(self.id, "unavailable", "No sea ice data for this place and time.", 0.0, 0.15, "ICE",
                           details={"reason": "environment cache has no sea-ice coverage"})
        c_ev, c_pre = _med(env[ev]["siconc"]), _med(env[pre]["siconc"]) if pre.any() else None
        th = _med(env[ev]["sithick"])
        point = None
        try:
            from alibi.explainers.sea_state import cache_of
            point = cache_of(ctx).sample(ctx.lat, ctx.lon, (ctx.event_start + ctx.event_end) / 2)
        except Exception:
            pass
        src = ((point or {}).get("sources") or {}).get("phy") or {}
        base_kn = ctx.baseline_kn if ctx.baseline_kn is not None else ctx.expected_kn
        obs = ctx.observed_kn
        drop = None if obs is None or base_kn is None else base_kn - obs
        pred = (loss_fraction(c_ev) - loss_fraction(c_pre)) * (base_kn or 0.0)
        details = {"siconc_event": _r(c_ev, 3), "siconc_baseline": _r(c_pre, 3), "sithick_m": _r(th),
                   "predicted_drop_kn": _r(pred), "observed_drop_kn": _r(drop), "ice_min_concentration": ICE_MIN,
                   "dataset": src.get("dataset"),
                   "method": "loss = 0.2 + 0.6*(c-0.3)/0.7 for c>=0.3; explains = predicted / observed drop"}
        common = dict(lamp="ICE", observed_at=src.get("observed_at"), source_reference=src.get("dataset"), details=details)
        pct = round((c_ev or 0.0) * 100)
        if c_ev is None or c_ev < ICE_MIN:
            return Finding(self.id, "neutral", f"No sea ice at the ship's position (concentration {pct} %).", 0.0, **common)
        if drop is None or drop < max(MIN_DROP_KN, MIN_DROP_FRAC * (base_kn or 0)):
            return Finding(self.id, "neutral", f"Sea ice is present (concentration {pct} %), but the ship did not slow.", 0.0, **common)
        explains = float(np.clip(pred / drop, 0.0, 1.0))
        thick = f", thickness {_r(th, 2)} m" if th is not None else ""
        if explains >= 0.2:
            return Finding(self.id, "supports_explanation",
                           f"Sea ice can account for about {round(explains * 100)} % of the slowdown: concentration {pct} %{thick}.",
                           explains, **common)
        return Finding(self.id, "neutral",
                       f"Sea ice is present (concentration {pct} %{thick}) but accounts for little of the slowdown.", explains, **common)


EXPLAINER = Ice()
