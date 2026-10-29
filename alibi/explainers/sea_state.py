"""Sea-state explainer (lamp WX): does the weather, waves or current account for the slowdown?

Why: a ship that slows in a gale is not behaving unusually, and a ship that slows in a flat calm is not
explained by the weather. We sample Copernicus Marine wind, waves and current from the cache along the part of the
track before the event (baseline) and during the event, ask `alibi.env.seaeffect` what each sea implies for a
typical merchant ship at the same speed and course, and compare the *change* in that effect with the observed
change in speed. explains = clip(predicted drop / observed drop, 0, 1). Fixed sentences only; numbers are filled in.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from alibi.env.cache import EnvCache, get_cache
from alibi.env.seaeffect import KN_PER_MS, default_length, expected_effect
from alibi.explainers.base import Context, Finding

ATTRIBUTION = ("Generated using E.U. Copernicus Marine Service Information: Baltic Sea Wave Analysis and Forecast "
               "(BALTICSEA_ANALYSISFORECAST_WAV_003_010, doi 10.48670/moi-00011), Baltic Sea Physics Analysis and "
               "Forecast (BALTICSEA_ANALYSISFORECAST_PHY_003_006) and Global Ocean Hourly Reprocessed Sea Surface "
               "Wind and Stress from Scatterometer and Model (WIND_GLO_PHY_L4_NRT_012_004 / _MY_012_006).")
MIN_DROP_KN = 0.5       # smaller observed drops are noise
MIN_DROP_FRAC = 0.05
CALM_WIND_MS, CALM_HS_M, CALM_PREDICTED_KN = 7.0, 1.0, 0.3


def cache_of(ctx: Context) -> EnvCache:
    return ctx.extra.get("envcache") or get_cache()


def env_along_track(ctx: Context):
    """Sampled environment for every track row, plus event/baseline masks. None if the track is unusable."""
    tr = ctx.track
    if tr is None or len(tr) == 0:
        return None
    t = tr["time"].to_numpy("float64")
    ok = np.isfinite(tr["lat"].to_numpy("float64")) & np.isfinite(tr["lon"].to_numpy("float64"))
    sub = tr.loc[ok, ["time", "lat", "lon"]]
    env = cache_of(ctx).sample_track(sub)
    ev = (sub["time"] >= ctx.event_start) & (sub["time"] <= ctx.event_end)
    pre = sub["time"] < ctx.event_start
    return tr.loc[ok], env, ev.to_numpy(), pre.to_numpy()


def _med(x) -> float | None:
    x = np.asarray(x, dtype="float64")
    x = x[np.isfinite(x)]
    return float(np.median(x)) if len(x) else None


def _r(x, n=2):
    return None if x is None else round(float(x), n)


def _dir_name(deg: float | None) -> str:
    if deg is None:
        return "unknown direction"
    names = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"]
    return names[int(((deg % 360) + 22.5) // 45) % 8]


class SeaState:
    id = "sea_state"
    title = "Sea state (wind, waves, current)"
    kind = "behaviour"
    attribution = ATTRIBUTION

    def _unavailable(self, why: str, penalty: float = 0.25) -> Finding:
        return Finding(self.id, "unavailable", f"No sea data for this place and time ({why}).", 0.0, penalty, "WX",
                       details={"reason": why})

    def evaluate(self, ctx: Context) -> Finding:
        got = env_along_track(ctx)
        if got is None:
            return self._unavailable("no track")
        tr, env, ev, pre = got
        have = {k: (env.attrs["sources_per_row"][k] != None).any() for k in ("wind", "wave", "phy")}  # noqa: E711
        if not any(have.values()):
            return self._unavailable("environment cache has no coverage")
        if not ev.any() or not pre.any():
            return self._unavailable("track has no part before the event" if not pre.any() else "no track in the event window", 0.15)

        base_kn = ctx.baseline_kn if ctx.baseline_kn is not None else ctx.expected_kn
        speed = base_kn if base_kn is not None else (_med(tr["sog"]) or 10.0)
        cog = tr["cog"].to_numpy("float64")
        cog = np.where(np.isfinite(cog), cog, ctx.cog_deg if ctx.cog_deg is not None else 0.0)
        length = default_length(ctx.vessel.get("cls"), ctx.vessel.get("length"))
        eff = expected_effect(env["wind_u"].to_numpy(), env["wind_v"].to_numpy(), env["cur_u"].to_numpy(),
                              env["cur_v"].to_numpy(), env["hs_m"].to_numpy(), cog_deg=cog, speed_kn=speed, length_m=length)
        d = np.asarray(eff["delta_kn"], dtype="float64") * np.ones(len(tr))
        base_eff, ev_eff = _med(d[pre]), _med(d[ev])
        predicted_drop = -(ev_eff - base_eff)
        times = tr["time"].to_numpy("float64")
        delta_series = [(int(t_), float(x - base_eff)) for t_, x in zip(times, d)]

        e_ = env[ev]
        wind, hs = _med(e_["wind_speed_ms"]), _med(e_["hs_m"])
        cur_kn = _med(np.asarray(eff["current_kn"], dtype="float64")[ev])
        mid = (ctx.event_start + ctx.event_end) / 2
        point = cache_of(ctx).sample(ctx.lat, ctx.lon, mid)
        sources = (point or {}).get("sources", {})
        details = {
            "event": {"wind_ms": _r(wind), "wind_from_deg": _r(_med(e_["wind_from_deg"]), 0), "hs_m": _r(hs),
                      "wave_from_deg": _r(_med(e_["wave_from_deg"]), 0), "tp_s": _r(_med(e_["tp_s"]), 1),
                      "current_along_course_kn": _r(cur_kn), "effect_kn": _r(ev_eff)},
            "baseline": {"wind_ms": _r(_med(env[pre]["wind_speed_ms"])), "hs_m": _r(_med(env[pre]["hs_m"])),
                         "effect_kn": _r(base_eff)},
            "predicted_drop_kn": _r(predicted_drop), "speed_used_kn": _r(speed), "length_m": length,
            "kwon": {k: _r(_med((np.asarray(eff[k], dtype="float64") * np.ones(len(tr)))[ev]), 3)
                     for k in ("beaufort", "rel_wind_deg", "c_beta", "c_u", "c_form", "wind_loss_pct")},
            "datasets": {k: v["dataset"] for k, v in sources.items()}, "missing": [k for k, v in have.items() if not v],
            "method": "Kwon (2008) speed loss + current along course; explains = predicted drop / observed drop",
        }
        penalty = 0.1 if details["missing"] else 0.0
        ref = ", ".join(sorted(set(details["datasets"].values()))) or None
        common = dict(lamp="WX", observed_at=(point or {}).get("observed_at"), source_reference=ref, details=details,
                      expected_delta_kn=delta_series, confidence_penalty=penalty)

        obs = ctx.observed_kn
        drop = None if obs is None or base_kn is None else base_kn - obs
        if drop is None or drop < max(MIN_DROP_KN, MIN_DROP_FRAC * (base_kn or 0)):
            return Finding(self.id, "neutral", "The ship did not slow enough for the sea state to matter.", 0.0, **common)
        explains = float(np.clip(predicted_drop / drop, 0.0, 1.0))
        details["observed_drop_kn"] = _r(drop)
        w_s, hs_s = _r(wind, 1), _r(hs, 1)
        calm = (wind is not None and wind < CALM_WIND_MS) and (hs is None or hs < CALM_HS_M) and predicted_drop < CALM_PREDICTED_KN
        if calm:
            return Finding(self.id, "weakens_explanation",
                           f"The sea was calm here: wind {w_s} m/s, waves {hs_s} m. It does not explain the slowdown.",
                           0.0, **common)
        if explains >= 0.2:
            return Finding(self.id, "supports_explanation",
                           f"The sea can account for about {round(explains * 100)} % of the slowdown: wind {w_s} m/s from the "
                           f"{_dir_name(_med(e_['wind_from_deg']))}, waves {hs_s} m, current {_r(cur_kn, 1)} kn along the course.",
                           explains, **common)
        return Finding(self.id, "neutral",
                       f"The sea would slow a ship by about {_r(max(predicted_drop, 0), 1)} kn here, little next to the "
                       f"{_r(drop, 1)} kn slowdown.", explains, **common)


EXPLAINER = SeaState()
