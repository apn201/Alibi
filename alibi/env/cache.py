"""Read side of the environmental cache: point and track lookups into per-day NetCDF files.

Why: assessments must never wait on Copernicus. Files are written once by `alibi.env.fetch`
(`<root>/<dataset_id>/<region>/<YYYYMMDD>.nc`), loaded lazily into memory as plain numpy arrays and kept in a
small LRU, so ~400 lookups cost milliseconds. Lookup is nearest hour and nearest grid cell; a land or NaN
cell falls back to the nearest wet cell within two cells (the models mask the coast differently).
"""
from __future__ import annotations

import datetime as dt
from collections import OrderedDict
from pathlib import Path

import numpy as np
import pandas as pd

from .fetch import KIND_DATASETS, REGIONS, default_root

KIND_VARS = {
    "wave": ["VHM0", "VMDR", "VTPK"],
    "phy": ["uo", "vo", "siconc", "sithick"],
    "wind": ["eastward_wind", "northward_wind"],
}
OUT_COLUMNS = ["wind_u", "wind_v", "wind_speed_ms", "wind_from_deg", "hs_m", "wave_from_deg", "tp_s",
               "cur_u", "cur_v", "siconc", "sithick"]
MAX_HOUR_GAP_S = 5400  # nearest hour must be within 1.5 h
_NEIGHBOURS = sorted(((dy, dx) for dy in range(-2, 3) for dx in range(-2, 3) if (dy, dx) != (0, 0)),
                     key=lambda o: (o[0] ** 2 + o[1] ** 2, o))


def _iso(t: float) -> str:
    return dt.datetime.fromtimestamp(float(t), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _nearest(axis: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Index of the nearest axis value (ascending axis) and whether x lies within one step of the axis extent."""
    n = len(axis)
    i = np.clip(np.searchsorted(axis, x), 1, n - 1)
    i = np.where(np.abs(x - axis[i - 1]) <= np.abs(axis[i] - x), i - 1, i)
    step = (axis[-1] - axis[0]) / max(n - 1, 1)
    return i, (x >= axis[0] - step) & (x <= axis[-1] + step)


class _Grid:
    def __init__(self, path: Path):
        import xarray as xr
        with xr.open_dataset(path) as ds:
            ds = ds.load()
        lat, lon = ds["latitude"].values.astype("float64"), ds["longitude"].values.astype("float64")
        self.flip_lat = lat[0] > lat[-1]
        self.lat = lat[::-1] if self.flip_lat else lat
        self.lon = lon
        self.t = ds["time"].values.astype("datetime64[s]").astype("int64")
        self.vars = {}
        for v in ds.data_vars:
            a = np.asarray(ds[v].values, dtype="float32")
            if a.ndim == 4:
                a = a[:, 0]
            self.vars[v] = a[:, ::-1] if self.flip_lat else a


class EnvCache:
    def __init__(self, root: str | Path | None = None, lru: int = 48):
        self.root = Path(root) if root else default_root()
        # A server fills data/envcache with recent days; the replay case days come with the repo.
        snap = Path(__file__).resolve().parents[2] / "snapshot" / "envcache"
        self.fallback = snap if root is None and snap != self.root else None
        self._lru: OrderedDict[Path, _Grid | None] = OrderedDict()
        self._max = lru

    def _grid(self, dataset: str, region: str, day: int) -> _Grid | None:
        rel = Path(dataset) / region / f"{dt.datetime.fromtimestamp(day * 86400, dt.timezone.utc):%Y%m%d}.nc"
        p = self.root / rel
        if not p.exists() and self.fallback is not None and (self.fallback / rel).exists():
            p = self.fallback / rel
        if p in self._lru:
            self._lru.move_to_end(p)
            return self._lru[p]
        g = None
        if p.exists():
            try:
                g = _Grid(p)
            except Exception:
                g = None
        if g is not None or len(self._lru) < self._max * 4:
            self._lru[p] = g
        while len(self._lru) > self._max:
            self._lru.popitem(last=False)
        return g

    def _lookup(self, kind: str, lat: np.ndarray, lon: np.ndarray, t: np.ndarray):
        """-> (values {var: array}, dataset id per point (object, None = no data), epoch of the hour used)."""
        n = len(lat)
        vals = {v: np.full(n, np.nan, "float32") for v in KIND_VARS[kind]}
        used = np.full(n, None, dtype=object)
        hour = np.full(n, np.nan)
        day = (t // 86400).astype("int64")
        for region, (lo0, lo1, la0, la1) in REGIONS.items():
            inreg = (lon >= lo0) & (lon <= lo1) & (lat >= la0) & (lat <= la1)
            if not inreg.any():
                continue
            for d in np.unique(day[inreg]):
                sel0 = inreg & (day == d)
                for ds_id in KIND_DATASETS[kind]:
                    sel = np.where(sel0 & (used == None))[0]  # noqa: E711
                    if not len(sel):
                        break
                    g = self._grid(ds_id, region, int(d))
                    if g is None:
                        continue
                    hi = np.clip(np.searchsorted(g.t, t[sel]), 1, max(len(g.t) - 1, 1)) if len(g.t) > 1 else np.zeros(len(sel), int)
                    if len(g.t) > 1:
                        hi = np.where(np.abs(t[sel] - g.t[hi - 1]) <= np.abs(g.t[hi] - t[sel]), hi - 1, hi)
                    gap = np.abs(t[sel] - g.t[hi])
                    iy, oky = _nearest(g.lat, lat[sel])
                    ix, okx = _nearest(g.lon, lon[sel])
                    ok = (gap <= MAX_HOUR_GAP_S) & oky & okx
                    sel, hi, iy, ix = sel[ok], hi[ok], iy[ok], ix[ok]
                    got = np.zeros(len(sel), bool)
                    for v in KIND_VARS[kind]:
                        a = g.vars.get(v)
                        if a is None:
                            continue
                        x = a[hi, iy, ix].copy()
                        miss = np.isnan(x)
                        if miss.any():
                            for dy, dx in _NEIGHBOURS:
                                m = np.where(miss)[0]
                                if not len(m):
                                    break
                                y2 = np.clip(iy[m] + dy, 0, a.shape[1] - 1)
                                x2 = np.clip(ix[m] + dx, 0, a.shape[2] - 1)
                                x[m] = a[hi[m], y2, x2]
                                miss = np.isnan(x)
                        vals[v][sel] = x
                        got |= ~np.isnan(x)
                    used[sel[got]] = ds_id
                    hour[sel[got]] = g.t[hi[got]]
        return vals, used, hour

    def sample_track(self, df: pd.DataFrame) -> pd.DataFrame:
        """Vectorised lookup for a frame with columns time (epoch s), lat, lon. Same index; NaN where no data."""
        lat = df["lat"].to_numpy("float64")
        lon = df["lon"].to_numpy("float64")
        t = df["time"].to_numpy("float64")
        out = pd.DataFrame(index=df.index, columns=OUT_COLUMNS, dtype="float64")
        srcs: dict[str, np.ndarray] = {}
        hrs: dict[str, np.ndarray] = {}
        w, w_ds, w_h = self._lookup("wind", lat, lon, t)
        v, v_ds, v_h = self._lookup("wave", lat, lon, t)
        c, c_ds, c_h = self._lookup("phy", lat, lon, t)
        u10, v10 = w["eastward_wind"].astype("float64"), w["northward_wind"].astype("float64")
        out["wind_u"], out["wind_v"] = u10, v10
        out["wind_speed_ms"] = np.hypot(u10, v10)
        out["wind_from_deg"] = np.degrees(np.arctan2(-u10, -v10)) % 360
        out["hs_m"], out["wave_from_deg"], out["tp_s"] = v["VHM0"], v["VMDR"], v["VTPK"]
        out["cur_u"], out["cur_v"] = c["uo"], c["vo"]
        out["siconc"], out["sithick"] = c["siconc"], c["sithick"]
        for k, ds_, h in (("wind", w_ds, w_h), ("wave", v_ds, v_h), ("phy", c_ds, c_h)):
            srcs[k], hrs[k] = ds_, h
        out.attrs["sources_per_row"] = srcs
        out.attrs["hours_per_row"] = hrs
        return out

    def sample(self, lat: float, lon: float, t_epoch: float) -> dict | None:
        """One point. None if no product has data there; else the fields plus `sources` {kind: {dataset, observed_at}}."""
        r = self.sample_track(pd.DataFrame({"time": [t_epoch], "lat": [lat], "lon": [lon]}))
        sources = {}
        for k in ("wind", "wave", "phy"):
            ds_id, h = r.attrs["sources_per_row"][k][0], r.attrs["hours_per_row"][k][0]
            if ds_id is not None:
                sources[k] = {"dataset": ds_id, "observed_at": _iso(h)}
        if not sources:
            return None
        row = {c: (None if pd.isna(r[c].iloc[0]) else float(r[c].iloc[0])) for c in OUT_COLUMNS}
        row["sources"] = sources
        row["observed_at"] = min(s["observed_at"] for s in sources.values())
        return row

    def coverage(self) -> dict:
        """For /health: per dataset and region, number of day files and first/last day."""
        out: dict[str, dict] = {}
        if not self.root.exists():
            return out
        for ds_dir in sorted(p for p in self.root.iterdir() if p.is_dir()):
            for reg in sorted(p for p in ds_dir.iterdir() if p.is_dir()):
                days = sorted(f.stem for f in reg.glob("*.nc"))
                if days:
                    out.setdefault(ds_dir.name, {})[reg.name] = {"days": len(days), "first": days[0], "last": days[-1]}
        return out


_default: EnvCache | None = None


def get_cache() -> EnvCache:
    global _default
    if _default is None:
        _default = EnvCache()
    return _default
