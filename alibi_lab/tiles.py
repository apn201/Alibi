"""A plain lat/lon tile grid and per-tile behaviour of moving vessels.

Tiles are DLAT x DLON degrees: 0.05 x 0.10 is about 5.6 x 5.5 km at 60N. A passage
is one vessel's consecutive run of positions inside one tile, so a ship anchored in
a tile all day counts once, and a ferry crossing it ten times counts ten times.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DLAT, DLON = 0.05, 0.10
MOVING_KN = 2.0


def tile_ids(lat, lon, dlat: float = DLAT, dlon: float = DLON):
    return np.floor(np.asarray(lat) / dlat).astype(np.int32), np.floor(np.asarray(lon) / dlon).astype(np.int32)


def passages(loc: pd.DataFrame, dlat: float = DLAT, dlon: float = DLON, moving_only: bool = True) -> pd.DataFrame:
    """One row per passage: mmsi, ti, tj, t0, t1, n, sog_median, cog_mean (circular)."""
    d = loc.dropna(subset=["lat", "lon"])
    if moving_only:
        d = d[d["sog"] >= MOVING_KN]
    ti, tj = tile_ids(d["lat"], d["lon"], dlat, dlon)
    d = d.assign(ti=ti, tj=tj)[["mmsi", "time", "ti", "tj", "sog", "cog"]]
    # new passage whenever vessel or tile changes, or 15 min without a report
    new = ((d["mmsi"].diff() != 0) | (d["ti"].diff() != 0) | (d["tj"].diff() != 0)
           | (d["time"].diff() > 900))
    d = d.assign(pid=new.cumsum())
    rad = np.radians(d["cog"])
    d = d.assign(cs=np.cos(rad), sn=np.sin(rad))
    agg = d.groupby("pid").agg(mmsi=("mmsi", "first"), ti=("ti", "first"), tj=("tj", "first"),
                               t0=("time", "first"), t1=("time", "last"), n=("time", "size"),
                               sog_median=("sog", "median"), cs=("cs", "mean"), sn=("sn", "mean"))
    agg["cog_mean"] = np.degrees(np.arctan2(agg["sn"], agg["cs"])) % 360
    return agg.drop(columns=["cs", "sn"]).reset_index(drop=True)


def tile_profile(pas: pd.DataFrame) -> pd.DataFrame:
    """Per tile: passages, vessels, speed distribution of passage medians."""
    g = pas.groupby(["ti", "tj"])
    prof = g.agg(passages=("mmsi", "size"), vessels=("mmsi", "nunique"),
                 sog_p25=("sog_median", lambda s: s.quantile(0.25)),
                 sog_p50=("sog_median", "median"),
                 sog_p75=("sog_median", lambda s: s.quantile(0.75))).reset_index()
    prof["lat"] = (prof["ti"] + 0.5) * DLAT
    prof["lon"] = (prof["tj"] + 0.5) * DLON
    return prof


def split_half_stability(pas: pd.DataFrame, split_time: float, min_passages: int) -> pd.DataFrame:
    """Median passage speed per tile before vs after split_time, for tiles with at least
    min_passages passages on each side. The honest test: a profile learnt on one period,
    checked on the next."""
    a = pas[pas["t0"] < split_time].groupby(["ti", "tj"])["sog_median"].agg(["size", "median"])
    b = pas[pas["t0"] >= split_time].groupby(["ti", "tj"])["sog_median"].agg(["size", "median"])
    j = a.join(b, lsuffix="_a", rsuffix="_b", how="inner")
    return j[(j["size_a"] >= min_passages) & (j["size_b"] >= min_passages)].reset_index()


def days_to_ready(prof: pd.DataFrame, hours_observed: float, need: int) -> pd.Series:
    """Days until each tile has `need` passages, if traffic continues at the observed rate."""
    per_day = prof["passages"] / (hours_observed / 24)
    return need / per_day
