"""Place: is this a place where ships of this kind go slower anyway?

Three pieces of evidence, the strongest counts:
    tile normal     median speed of this type group's segments in the 0.05 x 0.10 deg tile,
                    against the class prototype: a tile where cargo ships always run at 8 kn
                    explains a cargo ship doing 8 kn there.
    port approach   a tile where many segments of this group run under 5 kn (approaches,
                    anchorages, pilot boarding) explains part of the drop by that share.
    restrictions    Traficom restriction areas (Finnish waters): a speed limit explains the drop
                    down to the limit; a wake ban part of it. An anchoring ban is shown, not counted.
    stop area       the ship slowed or stopped in a grid cell where other ships habitually stop
                    (berths, anchorages, waiting areas; tools/stop_areas.py, learnt from AIS
                    history). An arrival explains most of a drop. A ship stopping where nobody
                    else ever stops gets nothing from this, which keeps a grounding question open.

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


STOP_CELL_DEG = 0.02   # rules._core.CELL_DEG
STOP_SHARE = 0.85      # an arrival at a known stop area explains this share of the drop


@lru_cache(maxsize=1)
def stop_cells() -> dict[tuple[int, int], int]:
    """(i, j) -> number of different ships seen stopped there; empty if the layer is missing."""
    path = config.PROFILE_DB / "stop_areas.parquet"
    if not path.exists():
        return {}
    import pandas as pd
    c = pd.read_parquet(path, columns=["i", "j", "ships"])
    return dict(zip(zip(c["i"].tolist(), c["j"].tolist()), c["ships"].tolist()))


def stop_area_near(points) -> int:
    """Most ships stopped in the cells (and neighbours) of any of the (lat, lon) points; 0 if none."""
    cells, best = stop_cells(), 0
    for lat, lon in points:
        i, j = int(np.floor(lat / STOP_CELL_DEG)), int(np.floor(lon / STOP_CELL_DEG))
        for a in (-1, 0, 1):
            for b in (-1, 0, 1):
                best = max(best, cells.get((i + a, j + b), 0))
    return best


@lru_cache(maxsize=1)
def own_stop_cells() -> dict[int, dict[tuple[int, int], int]]:
    """mmsi -> {(i, j): days this ship stopped there}: a ferry's own berth that no other ship uses."""
    path = config.PROFILE_DB / "own_stops.parquet"
    if not path.exists():
        return {}
    import pandas as pd
    out: dict[int, dict] = {}
    for m, i, j, d in pd.read_parquet(path).itertuples(index=False):
        out.setdefault(int(m), {})[(int(i), int(j))] = int(d)
    return out


def own_stop_near(mmsi, points) -> int:
    cells, best = own_stop_cells().get(int(mmsi or 0), {}), 0
    for lat, lon in points:
        i, j = int(np.floor(lat / STOP_CELL_DEG)), int(np.floor(lon / STOP_CELL_DEG))
        for a in (-1, 0, 1):
            for b in (-1, 0, 1):
                best = max(best, cells.get((i + a, j + b), 0))
    return best


def _event_points(ctx: Context) -> list[tuple[float, float]]:
    ev = ctx.event_track
    pts = [(ctx.lat, ctx.lon)]
    if len(ev):
        pts.append((float(ev["lat"].iloc[-1]), float(ev["lon"].iloc[-1])))
        slow = ev[ev["sog"] < 3]
        if len(slow):
            pts.append((float(slow["lat"].median()), float(slow["lon"].median())))
    return pts


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
        pts = _event_points(ctx)
        ships_stopped = stop_area_near(pts)
        own_days = own_stop_near(ctx.vessel.get("mmsi"), pts)
        if ships_stopped:
            det["stop_area_ships"] = ships_stopped
            if not det.get("anchoring_prohibited"):
                options.append((STOP_SHARE * dev, f"The ship slowed where other ships stop: {ships_stopped} different "
                                "ships have stopped within about 2 km of here (a berth, anchorage or waiting area)."))
        if own_days:
            det["own_stop_days"] = own_days
            options.append((STOP_SHARE * dev, f"This ship has stopped within about 2 km of here on {own_days} earlier "
                            "days: its own berth or regular waiting place."))
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
        ships_stopped = stop_area_near(_event_points(ctx))
        own_days = own_stop_near(ctx.vessel.get("mmsi"), _event_points(ctx))
        if own_days and not ships_stopped:
            det["own_stop_days"] = own_days
            return Finding(self.id, "supports_explanation", f"This ship has waited within about 2 km of here on "
                           f"{own_days} earlier days.", STOP_SHARE, 0.0, self.lamp, source_reference=ref, details=det)
        if ships_stopped:
            det["stop_area_ships"] = ships_stopped
            return Finding(self.id, "supports_explanation", f"Other ships wait here too: {ships_stopped} different ships "
                           "have stopped within about 2 km (an anchorage or waiting area).", STOP_SHARE, 0.0, self.lamp,
                           source_reference=ref, details=det)
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
