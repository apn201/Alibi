"""Test the hypothesis before using it: do ships really go slower when Copernicus says the sea is rough?

    python eval/hypothesis.py            -> eval/results/hypothesis.json, hypothesis.md, hypothesis.png

Every moving segment in the profile DB (Danish archive and our recording) that falls on a day the
environmental cache holds is compared with the same ship's own typical speed: ratio = segment
median speed / own profile speed. The sea at the segment's middle point and time comes from the
cache (wind 10 m, significant wave height, surface current). If the sea explains slowdowns, the
ratio should fall as wind and waves grow, and the share of clearly slow segments should rise.

Merchant ships only (cargo, tanker, passenger, M/L/XL), own profile from at least 10 hours.
Segments are short; the profile was fitted on the same data, so this measures association, not a
held-out prediction. Correlation is not causation: storms also change routes and schedules.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from alibi.env.cache import EnvCache  # noqa: E402

DB = ROOT / "data" / "derived" / "profile_db"
OUT = ROOT / "eval" / "results"
SLOW = 0.85  # a segment below 85 % of the ship's own speed counts as clearly slow
WIND_BINS = [0, 5, 8, 11, 14, 40]
HS_BINS = [0, 0.5, 1.0, 1.5, 2.5, 10]


def cached_days(cache: EnvCache) -> dict[str, set[str]]:
    """region -> days (YYYY-MM-DD) for which the wave product is cached."""
    out: dict[str, set[str]] = {}
    for ds, regions in cache.coverage().items():
        if "wav" not in ds:
            continue
        for reg in regions:
            out[reg] = {f"{f.stem[:4]}-{f.stem[4:6]}-{f.stem[6:8]}" for f in (cache.root / ds / reg).glob("*.nc")}
    return out


def load_segments(days: dict[str, set[str]]) -> pd.DataFrame:
    source_of = {"dk": "dk", "gof": "fi"}
    files = [DB / "segments" / source_of[r] / f"{d}.parquet" for r, ds in days.items() if r in source_of for d in ds]
    files = [f.as_posix() for f in files if f.exists()]
    if not files:
        return pd.DataFrame()
    q = f"""
        with s as (select * from read_parquet({files}, union_by_name=true)),
        k as (select mmsi, vessel_key, cls from '{(DB / 'vessel_keys.parquet').as_posix()}'),
        p as (select vessel_key, speed as own_speed, hours as own_hours
              from '{(DB / 'vessel_profiles.parquet').as_posix()}' where source = 'all')
        select s.mmsi, s.t0, s.t1, s.lat, s.lon, s.speed, s.minutes, s.source, k.cls, p.own_speed, p.own_hours
        from s join k using (mmsi) join p using (vessel_key)
        where p.own_hours >= 10 and p.own_speed >= 6
          and regexp_matches(k.cls, '^(cargo|tanker|passenger)/(M|L|XL)$')"""
    seg = duckdb.sql(q).df()
    seg["ratio"] = seg["speed"] / seg["own_speed"]
    seg["time"] = (seg["t0"] + seg["t1"]) / 2
    return seg


def table(seg: pd.DataFrame, col: str, bins: list[float], label: str) -> list[dict]:
    rows = []
    for iv, g in seg.groupby(pd.cut(seg[col], bins, right=False), observed=True):
        rows.append({label: f"{iv.left:g}-{iv.right:g}", "segments": len(g),
                     "median_ratio": round(float(g["ratio"].median()), 3),
                     "share_slow": round(float((g["ratio"] < SLOW).mean()), 3)})
    return rows


def main() -> int:
    cache = EnvCache()
    days = cached_days(cache)
    seg = load_segments(days)
    if seg.empty:
        print("no segments on cached days")
        return 1
    env = cache.sample_track(seg[["time", "lat", "lon"]])
    seg = seg.join(env[["wind_speed_ms", "hs_m", "cur_u", "cur_v"]])
    seg = seg.dropna(subset=["wind_speed_ms", "hs_m"])
    calm = seg[(seg["wind_speed_ms"] < 5) & (seg["hs_m"] < 0.5)]
    rough = seg[(seg["wind_speed_ms"] >= 11) | (seg["hs_m"] >= 1.5)]
    res = {
        "segments": len(seg), "ships": int(seg["mmsi"].nunique()),
        "days": {r: sorted(d) for r, d in days.items()},
        "by_source": seg.groupby("source").size().to_dict(),
        "spearman_ratio_wind": round(float(seg["ratio"].corr(seg["wind_speed_ms"], method="spearman")), 3),
        "spearman_ratio_hs": round(float(seg["ratio"].corr(seg["hs_m"], method="spearman")), 3),
        "calm": {"segments": len(calm), "median_ratio": round(float(calm["ratio"].median()), 3),
                 "share_slow": round(float((calm["ratio"] < SLOW).mean()), 3)},
        "rough": {"segments": len(rough), "median_ratio": round(float(rough["ratio"].median()), 3),
                  "share_slow": round(float((rough["ratio"] < SLOW).mean()), 3)},
        "by_wind": table(seg, "wind_speed_ms", WIND_BINS, "wind_ms"),
        "by_hs": table(seg, "hs_m", HS_BINS, "hs_m"),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "hypothesis.json").write_text(json.dumps(res, indent=1), encoding="utf-8")

    md = [f"# Does the sea explain slowdowns?\n",
          f"{res['segments']:,} moving segments of {res['ships']:,} merchant ships on the days the Copernicus cache holds.",
          f"Ratio = segment speed / the ship's own usual speed. Slow = below {SLOW:.0%}.\n",
          f"Spearman correlation, ratio vs wind: {res['spearman_ratio_wind']}; vs wave height: {res['spearman_ratio_hs']}.\n",
          f"| sea | segments | median ratio | share slow |", "|---|---|---|---|",
          f"| calm (wind < 5 m/s, Hs < 0.5 m) | {res['calm']['segments']:,} | {res['calm']['median_ratio']} | {res['calm']['share_slow']:.1%} |",
          f"| rough (wind >= 11 m/s or Hs >= 1.5 m) | {res['rough']['segments']:,} | {res['rough']['median_ratio']} | {res['rough']['share_slow']:.1%} |\n",
          "| wind m/s | segments | median ratio | share slow |", "|---|---|---|---|",
          *[f"| {r['wind_ms']} | {r['segments']:,} | {r['median_ratio']} | {r['share_slow']:.1%} |" for r in res["by_wind"]],
          "", "| Hs m | segments | median ratio | share slow |", "|---|---|---|---|",
          *[f"| {r['hs_m']} | {r['segments']:,} | {r['median_ratio']} | {r['share_slow']:.1%} |" for r in res["by_hs"]]]
    (OUT / "hypothesis.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(1, 2, figsize=(10, 3.6))
        for a, key, lab in ((ax[0], "by_wind", "wind_ms"), (ax[1], "by_hs", "hs_m")):
            rows = res[key]
            a.bar([r[lab] for r in rows], [r["share_slow"] * 100 for r in rows], color="#2c6aa8")
            a.set_xlabel("wind 10 m, m/s" if lab == "wind_ms" else "significant wave height, m")
            a.set_ylabel(f"% of segments below {SLOW:.0%} of own speed")
        fig.suptitle("Merchant ships vs Copernicus Marine sea state")
        fig.tight_layout()
        fig.savefig(OUT / "hypothesis.png", dpi=120)
    except ImportError:
        pass
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
