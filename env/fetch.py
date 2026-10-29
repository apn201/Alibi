"""Fetch Copernicus Marine fields into the read-through cache.

Why: every assessment in the same sea area and hour asks Copernicus the same question, so the
service never calls Copernicus per request. This module is the only writer of `data/envcache/`:
`<dataset_id>/<region>/<YYYYMMDD>.nc`, one file per UTC day, only the variables ALIBI needs,
surface only, dims (time, latitude, longitude). Days already present are skipped; missing days
are fetched in contiguous runs (one `subset` call per run) and split into day files.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import tempfile
from pathlib import Path

import pandas as pd

REGIONS = {  # lon_min, lon_max, lat_min, lat_max
    "gof": (21.0, 30.5, 59.0, 61.0),
    "dk": (7.5, 15.5, 54.0, 58.5),
}
WAVE = "cmems_mod_bal_wav_anfc_PT1H-i"
PHY = "cmems_mod_bal_phy_anfc_PT1H-i"
WIND_NRT = "cmems_obs-wind_glo_phy_nrt_l4_0.125deg_PT1H"
WIND_MY = "cmems_obs-wind_glo_phy_my_l4_0.125deg_PT1H"
# dataset -> (variables, first UTC day available, last UTC day available or None, surface depth range)
DATASETS = {
    WAVE: (["VHM0", "VMDR", "VTPK"], "2021-10-01", None, None),
    PHY: (["uo", "vo", "siconc", "sithick"], "2022-12-01", None, (0.0, 2.0)),
    WIND_NRT: (["eastward_wind", "northward_wind"], "2024-06-14", None, None),
    WIND_MY: (["eastward_wind", "northward_wind"], "2007-01-01", "2024-06-13", None),
}
KIND_DATASETS = {"wave": [WAVE], "phy": [PHY], "wind": [WIND_NRT, WIND_MY]}
PRODUCTS = {
    WAVE: "BALTICSEA_ANALYSISFORECAST_WAV_003_010", PHY: "BALTICSEA_ANALYSISFORECAST_PHY_003_006",
    WIND_NRT: "WIND_GLO_PHY_L4_NRT_012_004", WIND_MY: "WIND_GLO_PHY_L4_MY_012_006",
}
CASES = {  # name -> (region, start, end) UTC days inclusive
    "eagle_s": ("gof", "2024-12-24", "2024-12-26"),
    "fi_fleet": ("gof", "2026-10-04", "2026-10-07"),
    "recording": ("gof", "2026-10-04", "2026-10-29"),
    "dk_oct2025": ("dk", "2025-10-02", "2025-10-07"),
    "dk_feb2026": ("dk", "2026-01-31", "2026-02-08"),
    "dk_newyear": ("dk", "2025-12-30", "2026-01-04"),
    "dk_apr2026": ("dk", "2026-04-03", "2026-04-07"),
    "dk_jul2026": ("dk", "2026-07-01", "2026-07-05"),
}


def default_root() -> Path:
    return Path(os.environ.get("ALIBI_ENVCACHE") or Path(__file__).resolve().parents[2] / "data" / "envcache")


def credentials_present() -> bool:
    return (Path.home() / ".copernicusmarine" / ".copernicusmarine-credentials").exists()


def day_path(root: Path, dataset: str, region: str, day: dt.date) -> Path:
    return Path(root) / dataset / region / f"{day:%Y%m%d}.nc"


def _log(root: Path, msg: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    logging.getLogger("alibi.env.fetch").info(msg)
    with open(root / "fetch.log", "a", encoding="utf-8") as f:
        f.write(f"{dt.datetime.now(dt.timezone.utc):%Y-%m-%dT%H:%M:%SZ} {msg}\n")


def _days(start: str, end: str) -> list[dt.date]:
    return [d.date() for d in pd.date_range(start, end, freq="D")]


def _runs(days: list[dt.date]) -> list[list[dt.date]]:
    out: list[list[dt.date]] = []
    for d in days:
        if out and (d - out[-1][-1]).days == 1:
            out[-1].append(d)
        else:
            out.append([d])
    return out


def split_to_days(ds, dataset: str, region: str, root: Path) -> list[Path]:
    """Write a fetched (time, lat, lon[, depth]) Dataset as one file per UTC day. Returns written paths."""
    for dim in ("depth", "elevation"):
        if dim in ds.dims:
            ds = ds.isel({dim: 0}, drop=True)
    ds = ds[[v for v in DATASETS[dataset][0] if v in ds.data_vars]].astype("float32")
    written = []
    days = pd.to_datetime(ds["time"].values).normalize()
    for day in sorted(set(days)):
        sub = ds.isel(time=(days == day)).load()
        p = day_path(root, dataset, region, day.date())
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        sub.to_netcdf(tmp)
        tmp.replace(p)
        written.append(p)
    return written


def fetch(dataset: str, region: str, start: str, end: str, root: Path | None = None) -> dict:
    """Fetch UTC days start..end (inclusive) of one dataset for one region into the cache."""
    import copernicusmarine as cm
    import xarray as xr

    root = Path(root or default_root())
    variables, lo, hi, depth = DATASETS[dataset]
    lon0, lon1, lat0, lat1 = REGIONS[region]
    stats = {"dataset": dataset, "region": region, "skipped": 0, "fetched": 0, "out_of_range": 0, "bytes": 0, "errors": []}
    todo = []
    for d in _days(start, end):
        if str(d) < lo or (hi and str(d) > hi):
            stats["out_of_range"] += 1
        elif day_path(root, dataset, region, d).exists():
            stats["skipped"] += 1
        else:
            todo.append(d)
    for run in _runs(todo):
        a, b = run[0], run[-1]
        with tempfile.TemporaryDirectory(prefix="alibi_cm_") as tmp:
            try:
                kw = dict(dataset_id=dataset, variables=variables, minimum_longitude=lon0, maximum_longitude=lon1,
                          minimum_latitude=lat0, maximum_latitude=lat1,
                          start_datetime=f"{a}T00:00:00", end_datetime=f"{b}T23:00:00",
                          output_directory=tmp, output_filename="part.nc", overwrite=True, disable_progress_bar=True)
                if depth:
                    kw.update(minimum_depth=depth[0], maximum_depth=depth[1])
                cm.subset(**kw)
                with xr.open_dataset(Path(tmp) / "part.nc") as ds:
                    paths = split_to_days(ds, dataset, region, root)
                n = sum(p.stat().st_size for p in paths)
                stats["fetched"] += len(paths)
                stats["bytes"] += n
                _log(root, f"OK {dataset} {region} {a}..{b} files={len(paths)} bytes={n}")
            except Exception as e:  # keep going: other runs and datasets are independent
                stats["errors"].append(f"{a}..{b}: {e}")
                _log(root, f"FAIL {dataset} {region} {a}..{b}: {type(e).__name__}: {e}")
    return stats


def fetch_span(region: str, start: str, end: str, root: Path | None = None, pad_days: int = 0) -> list[dict]:
    """All needed datasets (waves, physics, the wind product that covers each day) for one region and span."""
    s = str(pd.Timestamp(start).date() - dt.timedelta(days=pad_days))
    e = str(pd.Timestamp(end).date() + dt.timedelta(days=pad_days))
    return [fetch(ds, region, s, e, root) for ds in (WAVE, PHY, WIND_NRT, WIND_MY)]
