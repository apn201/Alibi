"""The profile snapshot ALIBI judges against, loaded once at startup.

Two things come from the profile DB (`alibi_lab.profile_db`, rebuilt nightly):

    profiles   per vessel and per class: typical speed, its spread, hours of evidence
               (source == "all": the Danish archive and our own recording together)
    segments   one row per moving segment (~2.8M): who, when, where (median position), how fast.
               own_habit, place and fleet query these: this ship here before, ships of its kind
               in this tile, other ships nearby at the same time.

Reading 750 parquet files takes ~15 s, so the joined segment table (plus each segment's
vessel profile speed and type group) is written once to `data/derived/alibi_cache/` and
read back as numpy arrays (float32, sorted by start time) on later starts. The cache is
rebuilt when the profile DB files change.

Coverage: the segments exist only where and when we have AIS (config.COVERAGE). Outside it
the answer is "unavailable", never "nothing happened".
"""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import config

log = logging.getLogger("alibi.profiles")

# Ship-type groups (alibi_lab.profile_db); working vessels do not cruise and are not scored.
GROUPS = ["cargo", "tanker", "passenger", "high speed", "tug", "fishing", "pleasure", "service",
          "fishing/tug/special", "other", "unknown"]
WORKING_GROUPS = {"tug", "fishing", "pleasure", "service", "fishing/tug/special"}
GROUP_CODE = {g: i for i, g in enumerate(GROUPS)}
DLAT, DLON = 0.05, 0.10  # tile grid, as alibi_lab.tiles
LOOKBACK_S = 2 * 86400   # segments starting more than this before a query window are not searched


def km_between(lat0: float, lon0: float, lat, lon):
    """Equirectangular distance in km; good to well under 1 % at Baltic scales."""
    dy = (np.asarray(lat, dtype=np.float64) - lat0) * 110.57
    dx = (np.asarray(lon, dtype=np.float64) - lon0) * 111.32 * math.cos(math.radians(lat0))
    return np.hypot(dx, dy)


def coverage(lat: float, lon: float, t: int) -> str | None:
    """Which segment source covers this place and time ("dk", "fi"), or None."""
    for name, lo0, lo1, la0, la1, d0, d1 in config.COVERAGE:
        t0 = datetime.fromisoformat(d0).replace(tzinfo=timezone.utc).timestamp()
        t1 = datetime.fromisoformat(d1).replace(tzinfo=timezone.utc).timestamp()
        if lo0 <= lon <= lo1 and la0 <= lat <= la1 and t0 <= t < t1:
            return name
    return None


def tile_key(lat, lon, grp):
    ti = np.floor(np.asarray(lat) / DLAT).astype(np.int64)
    tj = np.floor(np.asarray(lon) / DLON).astype(np.int64)
    return ((ti + 4000) * 10000 + (tj + 4000)) * 16 + np.asarray(grp, dtype=np.int64)


@dataclass
class ProfileData:
    vessels: dict = field(default_factory=dict)   # vessel_key -> profile row (source all)
    classes: dict = field(default_factory=dict)   # cls -> profile row
    keys: dict = field(default_factory=dict)      # mmsi -> {vessel_key, name, group, length, imo, cls}
    imo_key: dict = field(default_factory=dict)   # imo -> vessel_key
    key_mmsis: dict = field(default_factory=dict)  # vessel_key -> [mmsi, ...]
    seg: dict = field(default_factory=dict)       # column -> numpy array, sorted by t0
    mmsi_order: np.ndarray | None = None          # argsort of seg["mmsi"]
    tile_keys: np.ndarray | None = None           # sorted tile_key(ti, tj, grp)
    tile_vals: np.ndarray | None = None           # per tile key: n, median speed, share of slow segments
    loaded_at: float = 0.0
    load_seconds: float = 0.0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return bool(self.vessels) and bool(self.classes)

    @property
    def segments_ok(self) -> bool:
        return bool(self.seg) and len(self.seg["t0"]) > 0

    # -- lookups ---------------------------------------------------------------------------

    def class_profile(self, cls: str) -> dict | None:
        """The class prototype, falling back to the best-evidenced class of the same group."""
        p = self.classes.get(cls)
        if p is not None and p["hours"] >= 3:
            return p
        grp = cls.rsplit("/", 1)[0]
        same = [v for k, v in self.classes.items() if k.rsplit("/", 1)[0] == grp and v["hours"] >= 3]
        if same:
            return max(same, key=lambda v: v["hours"])
        return self.classes.get("unknown/?") or max(self.classes.values(), key=lambda v: v["hours"])

    def segments_window(self, t_from: int, t_to: int) -> np.ndarray:
        """Indices of segments overlapping [t_from, t_to]."""
        t0 = self.seg["t0"]
        lo = np.searchsorted(t0, t_from - LOOKBACK_S, "left")
        hi = np.searchsorted(t0, t_to, "right")
        idx = np.arange(lo, hi)
        return idx[self.seg["t1"][idx] >= t_from]

    def segments_of(self, mmsis: list[int]) -> np.ndarray:
        m = self.seg["mmsi"][self.mmsi_order]
        out = []
        for x in mmsis:
            lo, hi = np.searchsorted(m, x, "left"), np.searchsorted(m, x, "right")
            out.append(self.mmsi_order[lo:hi])
        return np.concatenate(out) if out else np.array([], dtype=np.int64)

    def tile(self, lat: float, lon: float, group: str) -> dict | None:
        if self.tile_keys is None:
            return None
        k = int(tile_key(lat, lon, GROUP_CODE.get(group, GROUP_CODE["unknown"])))
        i = np.searchsorted(self.tile_keys, k)
        if i >= len(self.tile_keys) or self.tile_keys[i] != k:
            return None
        n, p50, slow = self.tile_vals[i]
        return {"segments": int(n), "median_speed_kn": float(p50), "slow_share": float(slow)}


# -- loading -------------------------------------------------------------------------------

def _stamp() -> dict:
    files = [config.PROFILE_DB / n for n in ("vessel_profiles.parquet", "vessel_keys.parquet")]
    segs = list((config.PROFILE_DB / "segments").glob("*/*.parquet"))
    return {"profile_version": config.PROFILE_VERSION, "cache_format": 2,
            "files": {f.name: f.stat().st_mtime for f in files if f.exists()},
            "segment_files": len(segs), "segment_newest": max((f.stat().st_mtime for f in segs), default=0)}


def _build_cache(path, stamp_path, stamp) -> None:
    import duckdb
    db = config.PROFILE_DB.as_posix()
    t = time.time()
    df = duckdb.sql(f"""
        with vp as (select vessel_key, speed from '{db}/vessel_profiles.parquet' where source = 'all')
        select s.mmsi::INTEGER AS mmsi, s.t0::BIGINT AS t0, s.t1::BIGINT AS t1, s.lat::FLOAT AS lat,
               s.lon::FLOAT AS lon, s.speed::FLOAT AS speed, (s.source = 'fi')::TINYINT AS src,
               coalesce(k."group", 'unknown') AS grp, vp.speed::FLOAT AS own_speed
        from read_parquet('{db}/segments/*/*.parquet', union_by_name=true) s
        left join '{db}/vessel_keys.parquet' k on k.mmsi = s.mmsi
        left join vp on vp.vessel_key = coalesce(k.vessel_key, 'MMSI' || s.mmsi::VARCHAR)
        order by s.t0""").df()
    df["grp"] = df["grp"].map(GROUP_CODE).fillna(GROUP_CODE["unknown"]).astype("int8")
    config.CACHE.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    # tile normal per type group: segment count, median speed, share of segments under 5 kn
    df["tk"] = tile_key(df["lat"].to_numpy(), df["lon"].to_numpy(), df["grp"].to_numpy())
    g = df.groupby("tk")["speed"]
    tiles = pd.DataFrame({"n": g.size(), "p50": g.median(),
                          "slow": df.assign(s=df["speed"] < 5)["s"].groupby(df["tk"]).mean()}).reset_index()
    tiles.to_parquet(config.CACHE / f"tiles-{config.PROFILE_VERSION}.parquet", index=False)
    stamp_path.write_text(json.dumps(stamp), encoding="utf-8")
    log.info("segment cache built in %.1f s (%d rows)", time.time() - t, len(df))


def load() -> ProfileData:
    t = time.time()
    pd_ = ProfileData()
    try:
        vp = pd.read_parquet(config.PROFILE_DB / "vessel_profiles.parquet")
        vp = vp[vp["source"] == "all"]
        cols = ["hours", "segments", "speed", "speed_iqr", "speed_spread", "name", "cls", "imo", "first_day", "last_day"]
        vp = vp.set_index("vessel_key")[cols]
        vp["imo"] = vp["imo"].astype("float64")
        pd_.vessels = vp.to_dict("index")
        cp = pd.read_parquet(config.PROFILE_DB / "class_profiles.parquet")
        pd_.classes = cp[cp["source"] == "all"].set_index("cls")[["hours", "segments", "speed", "speed_iqr",
                                                                   "speed_spread"]].to_dict("index")
        vk = pd.read_parquet(config.PROFILE_DB / "vessel_keys.parquet")
        vk["imo"] = vk["imo"].astype("float64")
        vk["group"] = vk["group"].astype(object)
        vk["name"] = vk["name"].astype(object)
        pd_.keys = vk.set_index("mmsi")[["vessel_key", "name", "group", "length", "imo", "cls"]].to_dict("index")
        for m, r in pd_.keys.items():
            pd_.key_mmsis.setdefault(r["vessel_key"], []).append(int(m))
            if r["imo"] == r["imo"]:
                pd_.imo_key[int(r["imo"])] = r["vessel_key"]
    except Exception as e:  # noqa: BLE001 - startup must survive a missing profile DB
        pd_.error = f"profiles: {e}"
        log.exception("profile load failed")
    try:
        path = config.CACHE / f"segments-{config.PROFILE_VERSION}.parquet"
        stamp_path = config.CACHE / f"segments-{config.PROFILE_VERSION}.json"
        stamp = _stamp()
        if not path.exists() or not stamp_path.exists() or json.loads(stamp_path.read_text()) != stamp:
            if stamp["segment_files"] == 0:
                raise FileNotFoundError("no segment files")
            _build_cache(path, stamp_path, stamp)
        import pyarrow.parquet as pq
        tab = pq.read_table(path)
        pd_.seg = {c: tab.column(c).to_numpy() for c in tab.column_names}
        pd_.mmsi_order = np.argsort(pd_.seg["mmsi"], kind="stable")
        tiles = pq.read_table(config.CACHE / f"tiles-{config.PROFILE_VERSION}.parquet")
        pd_.tile_keys = tiles.column("tk").to_numpy()
        pd_.tile_vals = np.column_stack([tiles.column(c).to_numpy() for c in ("n", "p50", "slow")]).astype(np.float32)
    except Exception as e:  # noqa: BLE001
        pd_.error = (pd_.error + "; " if pd_.error else "") + f"segments: {e}"
        log.exception("segment load failed")
    pd_.loaded_at = time.time()
    pd_.load_seconds = pd_.loaded_at - t
    log.info("profiles loaded in %.1f s", pd_.load_seconds)
    return pd_


_DATA: ProfileData | None = None


def get() -> ProfileData:
    global _DATA
    if _DATA is None:
        _DATA = load()
    return _DATA
