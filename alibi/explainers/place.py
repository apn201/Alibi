"""Place: is this a place where ships of this kind go slower anyway?

Three pieces of evidence, the strongest counts:
    tile normal     median speed of this type group's segments in the 0.05 x 0.10 deg tile,
                    against the class prototype: a tile where cargo ships always run at 8 kn
                    explains a cargo ship doing 8 kn there.
    port approach   a tile where many segments of this group run under 5 kn (approaches,
                    anchorages, pilot boarding) explains part of the drop by that share.
    restrictions    Traficom restriction areas (Finnish waters): a speed limit explains the drop
                    down to the limit; a wake ban part of it. An anchoring ban is shown, not counted.

For lingering in one place (corridor_loiter) only the stopping habit of the tile counts: where
LOITER_FULL of this kind of ship's segments run under 5 kn (an anchorage, a waiting area),
lingering is fully explained; less, proportionally. An anchoring ban there weakens it.
"""

from __future__ import annotations

import glob
import gzip
import json
from functools import lru_cache

import numpy as np

from .. import config
from ._util import SUPPORTS, deviation_kn, no_slowdown, share, unavailable, window_delta
from .base import Context, Finding

MIN_TILE_SEGMENTS = 5
SLOW_SHARE = 0.4      # a tile where this share of segments run under 5 kn is a port approach or anchorage
WAKE_BAN_SHARE = 0.3  # a wake ban explains this share of a drop (starting guess)
LOITER_FULL = 0.6


@lru_cache(maxsize=1)
def restriction_areas() -> tuple[list, str | None]:
    """Latest Traficom snapshot: [(bbox, rings, codes, limit, name)], file name."""
    files = sorted(glob.glob(str(config.CONTEXT / "restriction_areas" / "*" / "*" / "*" / "*.json.gz")))
    if not files:
        return [], None
    with gzip.open(files[-1], "rt", encoding="utf-8") as fh:
        doc = json.load(fh)
    out = []
    for f in doc.get("features", []):
        g, p = f.get("geometry") or {}, f.get("properties") or {}
        codes = {c.strip() for c in str(p.get("rajoitustyypit") or "").split(",")}
        if not codes & {"01", "02", "06"}:
            continue
        polys = [g["coordinates"]] if g.get("type") == "Polygon" else g.get("coordinates", []) if g.get("type") == "MultiPolygon" else []
        for poly in polys:
            ring = np.asarray(poly[0], dtype=float)
            bbox = (ring[:, 0].min(), ring[:, 0].max(), ring[:, 1].min(), ring[:, 1].max())
            out.append((bbox, [np.asarray(r, dtype=float) for r in poly], codes, p.get("suuruus"), p.get("nimisijainti"),
                        p.get("id")))
    return out, files[-1].replace("\\", "/").rsplit("/", 1)[-1]


def _inside(x: float, y: float, ring: np.ndarray) -> bool:
    xs, ys = ring[:, 0], ring[:, 1]
    x0, y0, x1, y1 = xs, ys, np.roll(xs, -1), np.roll(ys, -1)
    cross = ((y0 > y) != (y1 > y)) & (x < (x1 - x0) * (y - y0) / np.where(y1 == y0, 1e-12, y1 - y0) + x0)
    return bool(cross.sum() % 2)


def areas_at(lat: float, lon: float) -> list[dict]:
    hits = []
    for bbox, rings, codes, limit, name, aid in restriction_areas()[0]:
        if bbox[0] <= lon <= bbox[1] and bbox[2] <= lat <= bbox[3] and _inside(lon, lat, rings[0]) \
                and not any(_inside(lon, lat, h) for h in rings[1:]):
            hits.append({"id": aid, "codes": sorted(codes), "limit": limit, "name": name})
    return hits


class Place:
    id = "place"
    title = "Place: local normal speed, restriction areas, port approach"
    kind = "behaviour"
    attribution = "ALIBI profile DB; Traficom restriction areas (CC BY 4.0)"
    lamp = "PLC"

    def evaluate(self, ctx: Context) -> Finding:
        pdata, cov = ctx.extra["profiles"], ctx.extra.get("coverage")
        lo0, lo1, la0, la1 = config.FINNISH_WATERS
        finnish = lo0 <= ctx.lon <= lo1 and la0 <= ctx.lat <= la1
        if (cov is None or not pdata.segments_ok) and not finnish:
            return unavailable(self.id, "This place is outside the AIS history and restriction data ALIBI holds.",
                               self.lamp)
        if ctx.extra.get("measure") == "loiter":
            return self.loiter(ctx, pdata, cov, finnish)
        dev = deviation_kn(ctx)
        if dev is None or dev <= 0:
            return no_slowdown(self.id, self.lamp)
        group = ctx.vessel.get("group") or "unknown"
        class_kn = ctx.extra.get("class_speed")
        det: dict = {"group": group, "class_speed_kn": class_kn, "coverage": cov}
        options = []  # (delta kn, sentence)
        tile = pdata.tile(ctx.lat, ctx.lon, group) if cov else None
        if tile and tile["segments"] >= MIN_TILE_SEGMENTS and class_kn:
            det["tile"] = {k: round(v, 3) for k, v in tile.items()}
            d_tile = max(0.0, class_kn - tile["median_speed_kn"])
            options.append((d_tile, f"Ships of this kind usually run at {tile['median_speed_kn']:.1f} kn in this "
                            f"area, below their class's typical {class_kn:.1f} kn ({tile['segments']} passages)."))
            if tile["slow_share"] >= SLOW_SHARE:
                options.append((tile["slow_share"] * dev, f"{tile['slow_share'] * 100:.0f} % of passages of this "
                                "kind of ship in this area are under 5 kn, as near a port approach or anchorage."))
        elif cov:
            det["tile"] = {"segments": tile["segments"] if tile else 0}
        areas = areas_at(ctx.lat, ctx.lon) if finnish else []
        if finnish:
            det["restriction_areas"] = areas
            det["restriction_snapshot"] = restriction_areas()[1]
        for a in areas:
            if "01" in a["codes"] and a["limit"]:
                limit_kn = float(a["limit"]) / 1.852  # km/h on inland and coastal Finnish limits
                options.append((max(0.0, ctx.expected_kn - limit_kn), f"The event lies in a {float(a['limit']):.0f} "
                                f"km/h speed-limit area ({limit_kn:.1f} kn)."))
            if "02" in a["codes"]:
                options.append((WAKE_BAN_SHARE * dev, "The event lies in an area where making waves is prohibited."))
        if any("06" in a["codes"] for a in areas):
            det["anchoring_prohibited"] = True
        if not options:
            return Finding(self.id, "neutral", "There is too little traffic of this kind here to say what is normal, "
                           "and no restriction area applies.", lamp=self.lamp, details=det,
                           source_reference=f"profile_db tiles ({cov})" if cov else det.get("restriction_snapshot"))
        delta, sentence = max(options, key=lambda o: o[0])
        e = share(delta, ctx)
        det.update(explains=round(e, 3), slower_here_kn=round(delta, 2))
        ref = "; ".join(x for x in (f"profile_db tiles ({cov})" if cov else None, det.get("restriction_snapshot")) if x)
        if e >= SUPPORTS:
            return Finding(self.id, "supports_explanation", sentence, e, 0.0, self.lamp, source_reference=ref,
                           details=det, expected_delta_kn=window_delta(ctx, delta))
        if tile and tile["segments"] >= MIN_TILE_SEGMENTS and tile["median_speed_kn"] >= ctx.expected_kn * 0.9 \
                and tile["slow_share"] < 0.2:
            return Finding(self.id, "weakens_explanation", f"Ships of this kind usually keep "
                           f"{tile['median_speed_kn']:.1f} kn in this area; the place does not explain the drop.",
                           e, 0.0, self.lamp, source_reference=ref, details=det)
        return Finding(self.id, "neutral", "The place explains little of the drop.", e, 0.0, self.lamp,
                       source_reference=ref, details=det,
                       expected_delta_kn=window_delta(ctx, delta) if delta > 0 else None)

    def loiter(self, ctx: Context, pdata, cov, finnish: bool) -> Finding:
        group = ctx.vessel.get("group") or "unknown"
        tile = pdata.tile(ctx.lat, ctx.lon, group) if cov and pdata.segments_ok else None
        areas = areas_at(ctx.lat, ctx.lon) if finnish else []
        det = {"group": group, "coverage": cov, "tile": tile, "restriction_areas": areas}
        ref = f"profile_db tiles ({cov})" if cov else restriction_areas()[1]
        if any("06" in a["codes"] for a in areas):
            return Finding(self.id, "weakens_explanation", "Anchoring is prohibited in this area, so lingering here "
                           "is not explained by the place.", 0.0, 0.0, self.lamp, source_reference=ref, details=det)
        if not tile or tile["segments"] < MIN_TILE_SEGMENTS:
            return Finding(self.id, "neutral", "There is too little traffic of this kind here to say whether ships "
                           "usually linger.", lamp=self.lamp, source_reference=ref, details=det)
        e = min(1.0, tile["slow_share"] / LOITER_FULL)
        det["explains"] = round(e, 3)
        pct = tile["slow_share"] * 100
        if e >= SUPPORTS:
            return Finding(self.id, "supports_explanation", f"{pct:.0f} % of passages of this kind of ship in this "
                           "area are under 5 kn, as at an anchorage or waiting area.", e, 0.0, self.lamp,
                           source_reference=ref, details=det)
        return Finding(self.id, "weakens_explanation", f"Ships of this kind rarely slow down in this area "
                       f"({pct:.0f} % of passages under 5 kn).", e, 0.0, self.lamp, source_reference=ref, details=det)


EXPLAINER = Place()
