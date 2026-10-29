# Copernicus Marine in ALIBI

Sea state (WX) and ice (ICE) are two explainers: they say how much of a slowdown the sea accounts for. They never
call Copernicus per request; they read a local cache filled by `tools/fetch_copernicus.py`.

## Products

| Role | Dataset id | Product (DOI) | Variables used | Grid, time |
|---|---|---|---|---|
| Waves | `cmems_mod_bal_wav_anfc_PT1H-i` | BALTICSEA_ANALYSISFORECAST_WAV_003_010 (10.48670/moi-00011) | VHM0 (Hs), VMDR (mean wave direction, from), VTPK (peak period) | 1 nautical mile (~0.0167 x 0.0278 deg), hourly, 2021-10 to now + forecast |
| Current, ice | `cmems_mod_bal_phy_anfc_PT1H-i` | BALTICSEA_ANALYSISFORECAST_PHY_003_006 | uo, vo (first level, ~0.5 m), siconc, sithick | ~1 nm, hourly, 2022-12 to now + forecast |
| Wind (2024-06-14 on) | `cmems_obs-wind_glo_phy_nrt_l4_0.125deg_PT1H` | WIND_GLO_PHY_L4_NRT_012_004 | eastward_wind, northward_wind (10 m) | 0.125 deg, hourly |
| Wind (before) | `cmems_obs-wind_glo_phy_my_l4_0.125deg_PT1H` | WIND_GLO_PHY_L4_MY_012_006 | same | 0.125 deg, hourly |

Why these: the Baltic models cover the Gulf of Finland, the Danish straits and the Kattegat at ship scale; the wind
is observation-based (scatterometer plus model) and global, so it also covers dates before the Baltic wind forcing
was published. The physics dataset version 202411 is announced to retire on 2027-01-12.

## Licence and attribution

Copernicus Marine Service data are free to use with attribution. Wherever a result built on them is shown:

> Generated using E.U. Copernicus Marine Service Information.

The explainers carry the longer form (product names, ids and the wave DOI) in `EXPLAINER.attribution`, and each
Finding records the dataset ids and the hour of the data used (`source_reference`, `observed_at`).

## Cache layout

```
data/envcache/<dataset_id>/<region>/<YYYYMMDD>.nc     one file per UTC day, 24 hourly steps
data/envcache/fetch.log                               one line per fetch run
```
Regions: `gof` lon 21-30.5, lat 59-61; `dk` lon 7.5-15.5, lat 54-58.5. Dims (time, latitude, longitude), float32,
surface only, only the variables above, zlib-compressed. Not tracked by git. Override the root with `ALIBI_ENVCACHE`.

```
python tools/fetch_copernicus.py --all-cases
python tools/fetch_copernicus.py --case eagle_s
python tools/fetch_copernicus.py --region dk --start 2026-02-01 --end 2026-02-07 [--pad-days 1]
```
Needs `copernicusmarine login` once (credentials stay in `~/.copernicusmarine`). Days already in the cache are
skipped; missing days are fetched in contiguous runs. Cases: eagle_s, fi_fleet, recording, dk_oct2025, dk_feb2026,
dk_newyear, dk_apr2026, dk_jul2026 (see `alibi/env/fetch.py`).

Read side: `alibi.env.EnvCache(root).sample(lat, lon, t)`, `.sample_track(df)`, `.coverage()`. Nearest hour (within
1.5 h) and nearest cell; a land or NaN cell uses the nearest wet cell within two cells. About 400 lookups take
a few milliseconds once the day files are loaded.

## Model

See the docstrings of `alibi/env/seaeffect.py` (current along course; Kwon's speed loss in wind and waves, with
references and the stated approximation of the speed coefficient) and the two explainers. Fixed sentences only.

## How the cost scales

One download per product, hour and area, shared by every assessment in that area. A thousand assessments about the
Gulf of Finland at 10:00 cost one hourly update, not a thousand calls. In production the same layout moves to object
storage (tiles keyed by product, variable, hour, area) and a scheduled job fetches each new analysis and forecast
run; the service only reads. For the hackathon the cache is local disk and holds the demo cases plus the replay days.
