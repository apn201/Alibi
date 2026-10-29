"""Tests for the environmental cache, the sea-effect model and the two explainers, on synthetic cache files."""
from __future__ import annotations

import datetime as dt
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from alibi.env import fetch as F  # noqa: E402
from alibi.env.cache import EnvCache  # noqa: E402
from alibi.env.seaeffect import current_along_course, expected_effect  # noqa: E402
from alibi.explainers import ice, sea_state  # noqa: E402
from alibi.explainers.base import Context  # noqa: E402

DAY = dt.date(2026, 10, 5)
T0 = int(dt.datetime(2026, 10, 5, 0, tzinfo=dt.timezone.utc).timestamp())


def write_day(root, dataset, vars_: dict, day=DAY, region="gof", nan_at=None):
    lat = np.arange(59.0, 61.01, 0.1)
    lon = np.arange(21.0, 30.51, 0.1)
    t = pd.date_range(f"{day} 00:00", periods=24, freq="h")
    data = {}
    for k, v in vars_.items():
        a = np.full((24, len(lat), len(lon)), v, "float32")
        if nan_at is not None:
            a[:, nan_at[0], nan_at[1]] = np.nan
        data[k] = (("time", "latitude", "longitude"), a)
    p = F.day_path(root, dataset, region, day)
    p.parent.mkdir(parents=True, exist_ok=True)
    xr.Dataset(data, coords={"time": t, "latitude": lat, "longitude": lon}).to_netcdf(p)


def make_env(root, wind=(0.0, 0.0), hs=0.3, cur=(0.0, 0.0), ice_c=0.0, wave_dir=270.0):
    write_day(root, F.WAVE, {"VHM0": hs, "VMDR": wave_dir, "VTPK": 5.0})
    write_day(root, F.PHY, {"uo": cur[0], "vo": cur[1], "siconc": ice_c, "sithick": 0.3 * ice_c})
    write_day(root, F.WIND_NRT if DAY >= dt.date(2024, 6, 14) else F.WIND_MY,
              {"eastward_wind": wind[0], "northward_wind": wind[1]})


def make_ctx(env: EnvCache, base=12.0, obs=8.0, cog=90.0):
    n = 240  # minutes, 05:00..09:00 UTC
    t = T0 + 5 * 3600 + np.arange(n) * 60
    sog = np.where(t < T0 + 7 * 3600, base, obs)
    tr = pd.DataFrame({"time": t, "lat": 60.0, "lon": np.linspace(24.0, 25.0, n), "sog": sog, "cog": cog,
                       "heading": cog, "pos_acc": 1, "raim": 0})
    return Context(track=tr, event_start=T0 + 7 * 3600, event_end=T0 + 9 * 3600 - 60, lat=60.0, lon=24.7,
                   vessel={"cls": "cargo/L", "length": 170.0}, expected_kn=base, observed_kn=obs, baseline_kn=base,
                   cog_deg=cog, unusual=0.6, extra={"envcache": env})


def test_sample_point_and_nearest_hour(tmp_path):
    make_env(tmp_path, wind=(3.0, 4.0), hs=1.5, cur=(0.2, -0.1))
    c = EnvCache(tmp_path)
    s = c.sample(60.02, 24.03, T0 + 3 * 3600 + 1500)
    assert s["wind_speed_ms"] == pytest.approx(5.0, abs=1e-4)
    assert s["wind_from_deg"] == pytest.approx(216.87, abs=0.1)  # blowing towards north-east -> from south-west
    assert s["hs_m"] == pytest.approx(1.5) and s["cur_u"] == pytest.approx(0.2, abs=1e-5)
    assert s["sources"]["wave"]["dataset"] == F.WAVE
    assert s["observed_at"] == "2026-10-05T03:00:00Z"
    assert c.sample(60.0, 24.0, T0 + 5 * 86400) is None  # no file
    assert c.sample(50.0, 5.0, T0) is None               # outside any region


def test_land_cell_uses_nearest_wet_and_coverage(tmp_path):
    write_day(tmp_path, F.WAVE, {"VHM0": 2.0, "VMDR": 90.0, "VTPK": 5.0}, nan_at=(10, 30))
    c = EnvCache(tmp_path)
    s = c.sample(60.0, 24.0, T0 + 3600)  # exactly the NaN cell (lat idx 10, lon idx 30)
    assert s["hs_m"] == pytest.approx(2.0)
    assert c.coverage()[F.WAVE]["gof"]["days"] == 1


def test_sample_track_is_fast(tmp_path):
    make_env(tmp_path, wind=(5.0, 0.0))
    c = EnvCache(tmp_path)
    df = pd.DataFrame({"time": T0 + np.linspace(0, 80000, 400), "lat": 60.0, "lon": np.linspace(22, 29, 400)})
    c.sample_track(df)  # warm
    t0 = time.perf_counter()
    r = c.sample_track(df)
    assert time.perf_counter() - t0 < 0.1
    assert r["wind_speed_ms"].notna().all() and len(r) == 400


def test_current_component_sign():
    assert current_along_course(1.0, 0.0, 90.0) == pytest.approx(1.944, abs=0.01)    # eastward current, heading east: helps
    assert current_along_course(1.0, 0.0, 270.0) == pytest.approx(-1.944, abs=0.01)  # heading west: against
    assert current_along_course(1.0, 0.0, 0.0) == pytest.approx(0.0, abs=1e-9)       # across


def test_kwon_monotonic_and_direction():
    kw = dict(cur_u=0.0, cur_v=0.0, hs_m=1.0, cog_deg=0.0, speed_kn=12.0, length_m=150.0)
    loss = lambda w: float(expected_effect(0.0, -w, **kw)["wind_loss_kn"])  # wind from north = head sea for cog 0
    assert loss(4) < loss(8) < loss(12) < loss(16)
    head = float(expected_effect(0.0, -10.0, **kw)["wind_loss_kn"])
    follow = float(expected_effect(0.0, 10.0, **kw)["wind_loss_kn"])
    beam = float(expected_effect(-10.0, 0.0, **kw)["wind_loss_kn"])
    assert head > beam > follow >= 0
    assert 0.02 < head / 12 < 0.5
    assert 0.05 < float(expected_effect(0.0, -12.3, **kw)["wind_loss_kn"]) / 12 < 0.2  # BN 6 head: about 10 %
    assert float(expected_effect(0.0, 0.0, **kw)["wind_loss_kn"]) < 0.05


def test_sea_state_supports_in_gale(tmp_path):
    make_env(tmp_path, wind=(0.0, -16.0), hs=3.0)  # wind from north; ship heading north-ish
    ctx = make_ctx(EnvCache(tmp_path), cog=0.0, base=12.0, obs=8.0)
    # calm before: rewrite baseline hours by using a track whose baseline sits in same sea -> change is ~0, so use fresh data
    f = sea_state.EXPLAINER.evaluate(ctx)
    # same gale before and during: the *change* is ~0, so the gale does not explain a sudden drop
    assert f.status in ("neutral", "weakens_explanation") and f.explains < 0.2


def test_sea_state_gale_arrives_explains(tmp_path):
    root = tmp_path
    # hours 0-6 calm, 7+ gale from the north
    for h_range, wind, hs in (((0, 7), (0.0, -1.0), 0.3), ((7, 24), (0.0, -18.0), 3.5)):
        pass
    write_day(root, F.PHY, {"uo": 0.0, "vo": 0.0, "siconc": 0.0, "sithick": 0.0})
    write_day(root, F.WAVE, {"VHM0": 0.3, "VMDR": 0.0, "VTPK": 4.0})
    write_day(root, F.WIND_NRT, {"eastward_wind": 0.0, "northward_wind": -1.0})
    p = F.day_path(root, F.WIND_NRT, "gof", DAY)
    ds = xr.load_dataset(p)
    ds["northward_wind"][7:] = -18.0
    ds.to_netcdf(p.with_suffix(".x"))
    p.with_suffix(".x").replace(p)
    pw = F.day_path(root, F.WAVE, "gof", DAY)
    dw = xr.load_dataset(pw)
    dw["VHM0"][7:] = 3.5
    dw.to_netcdf(pw.with_suffix(".x"))
    pw.with_suffix(".x").replace(pw)
    f = sea_state.EXPLAINER.evaluate(make_ctx(EnvCache(root), cog=0.0, base=12.0, obs=8.0))
    assert f.status == "supports_explanation" and f.explains >= 0.2
    assert f.expected_delta_kn and f.expected_delta_kn[-1][1] < f.expected_delta_kn[0][1]
    assert F.WAVE in (f.source_reference or "") and "Copernicus" in sea_state.EXPLAINER.attribution


def test_sea_state_calm_weakens_and_no_data_unavailable(tmp_path):
    make_env(tmp_path, wind=(2.0, 0.0), hs=0.2)
    f = sea_state.EXPLAINER.evaluate(make_ctx(EnvCache(tmp_path)))
    assert f.status == "weakens_explanation" and "The sea was calm here" in f.summary and f.lamp == "WX"
    empty = sea_state.EXPLAINER.evaluate(make_ctx(EnvCache(tmp_path / "nothing")))
    assert empty.status == "unavailable" and empty.confidence_penalty == pytest.approx(0.25)


def test_ice_statuses(tmp_path):
    make_env(tmp_path / "a", ice_c=0.0)
    assert ice.EXPLAINER.evaluate(make_ctx(EnvCache(tmp_path / "a"))).status == "neutral"
    make_env(tmp_path / "b", ice_c=0.9)
    # ice is the same before and during, so the change it predicts is zero
    assert ice.EXPLAINER.evaluate(make_ctx(EnvCache(tmp_path / "b"))).explains == 0.0
    assert ice.loss_fraction(0.2) == 0.0 and ice.loss_fraction(1.0) == pytest.approx(0.8)
    assert ice.EXPLAINER.evaluate(make_ctx(EnvCache(tmp_path / "none"))).status == "unavailable"


def test_ice_arrives_explains(tmp_path):
    write_day(tmp_path, F.PHY, {"uo": 0.0, "vo": 0.0, "siconc": 0.0, "sithick": 0.0})
    p = F.day_path(tmp_path, F.PHY, "gof", DAY)
    ds = xr.load_dataset(p)
    ds["siconc"][7:] = 0.9
    ds["sithick"][7:] = 0.3
    ds.to_netcdf(p.with_suffix(".x"))
    p.with_suffix(".x").replace(p)
    f = ice.EXPLAINER.evaluate(make_ctx(EnvCache(tmp_path), base=12.0, obs=6.0))
    assert f.status == "supports_explanation" and f.explains > 0.5 and f.lamp == "ICE"
