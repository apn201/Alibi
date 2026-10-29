"""Notices: was a navigational warning in force near the event?

Traficom's navigational warnings (areas, points, lines) as recorded by our context recorder:
the latest snapshot at or before the event end is what was in force. We hold these for
Finnish waters from the first recorded snapshot only; elsewhere and earlier the source is unavailable.
A warning within NEAR_KM explains part of a drop (works, buoys, closures make ships slow);
the share is a starting guess. The warning text itself is quoted in `details`, not summarised.
"""

from __future__ import annotations

import glob
import gzip
import json
from datetime import datetime, timezone
from functools import lru_cache

import numpy as np

from .. import config
from ..profiles import km_between
from ._util import SUPPORTS, deviation_kn, iso, no_slowdown, share, unavailable, window_delta
from .base import Context, Finding

NEAR_KM = 2.0
LIST_KM = 5.0
EXPLAINS = 0.3
LAYERS = ("nav_warnings_a", "nav_warnings_p", "nav_warnings_l")


def _stamp(path: str) -> int:
    s = path.replace("\\", "/").rsplit("-", 1)[-1].split(".")[0]  # 20261019T083623Z
    return int(datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).timestamp())


@lru_cache(maxsize=1)
def snapshots() -> dict[str, list[tuple[int, str]]]:
    return {layer: sorted((_stamp(f), f) for f in glob.glob(str(config.CONTEXT / layer / "*" / "*" / "*" / "*.json.gz")))
            for layer in LAYERS}


@lru_cache(maxsize=64)
def _features(path: str) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        doc = json.load(fh)
    out = []
    for f in doc.get("features", []):
        coords = np.asarray(_flatten((f.get("geometry") or {}).get("coordinates", [])), dtype=float).reshape(-1, 2)
        p = f.get("properties") or {}
        out.append({"coords": coords, "id": p.get("MESSAGESERIESIDENTIFIERINTEROPERABILITYIDENTIFIER"),
                    "type": p.get("NAVWARNTYPEGENERAL_EN") or p.get("WARNINGINFORMATIONNAVWARNTYPEDETAILS_EN"),
                    "text": p.get("WARNINGINFORMATION_EN"), "published": p.get("PUBLICATIONTIME")})
    return out


def _flatten(c):
    if c and isinstance(c[0], (int, float)):
        return [c[:2]]
    return [p for x in c for p in _flatten(x)]


class Notices:
    id = "notices"
    title = "Navigational warnings in force"
    kind = "behaviour"
    attribution = "Traficom navigational warnings (CC BY 4.0)"
    lamp = "PLC"

    def evaluate(self, ctx: Context) -> Finding:
        lo0, lo1, la0, la1 = config.FINNISH_WATERS
        snaps = snapshots()
        first = min((v[0][0] for v in snaps.values() if v), default=None)
        if not (lo0 <= ctx.lon <= lo1 and la0 <= ctx.lat <= la1):
            return unavailable(self.id, "Navigational warnings are held for Finnish waters only.", self.lamp, 0.05)
        if first is None or ctx.event_end < first:
            since = iso(first)[:10] if first else "no date"
            return unavailable(self.id, f"Navigational warnings are held from {since} only.", self.lamp, 0.05)
        used, near = [], []
        for layer, layer_snaps in snaps.items():
            before = [s for s in layer_snaps if s[0] <= ctx.event_end]
            if not before:
                continue
            path = before[-1][1]
            used.append(path.replace("\\", "/").rsplit("/", 1)[-1])
            for w in _features(path):
                if not len(w["coords"]) or (w["published"] and w["published"] > iso(ctx.event_end)):
                    continue
                d = float(km_between(ctx.lat, ctx.lon, w["coords"][:, 1], w["coords"][:, 0]).min())
                if d <= LIST_KM:
                    near.append({"distance_km": round(d, 2), "layer": layer,
                                 **{k: w[k] for k in ("id", "type", "text", "published")}})
        if not used:
            return unavailable(self.id, "No navigational warning snapshot covers the event time.", self.lamp, 0.05)
        near.sort(key=lambda w: w["distance_km"])
        det = {"warnings_within_5km": near, "snapshots": used}
        ref = "Traficom navigational warnings: " + ", ".join(used)
        if not near or near[0]["distance_km"] > NEAR_KM:
            return Finding(self.id, "neutral", f"No navigational warning was in force within {NEAR_KM:.0f} km of "
                           "the event.", lamp=self.lamp, source_reference=ref, details=det)
        dev = deviation_kn(ctx)
        if dev is None or dev <= 0:
            return no_slowdown(self.id, self.lamp)
        delta = EXPLAINS * dev
        e = share(delta, ctx)
        status = "supports_explanation" if e >= SUPPORTS else "neutral"
        return Finding(self.id, status, f"A navigational warning was in force {near[0]['distance_km']:.1f} km from "
                       f"the event ({near[0]['id']}).", e, 0.0, self.lamp, source_reference=ref, details=det,
                       expected_delta_kn=window_delta(ctx, delta))


EXPLAINER = Notices()
