"""The profile database: segments from every source, ship identities, and profiles on top.

    data/derived/profile_db/
        segments/{source}/{YYYY-MM-DD}.parquet   one row per moving segment (profiles.segments)
                                                   source: "dk" = Danish archive, "fi" = our Digitraffic recording
        identities.parquet                       every (mmsi, imo, name, callsign, type, length) seen, with dates
        vessel_profiles.parquet                  per vessel_key and source, plus "all"
        class_profiles.parquet                   per prototype class and source, plus "all"
        profiles.duckdb                          views over all of the above, for ad-hoc queries

vessel_key: "IMO<n>" when the ship has ever reported an IMO number, else "MMSI<n>", so a
ship keeps its history through a change of MMSI or flag. Derived and disposable: rebuilt
from the recorder files and the compacted DMA days. Segments are written per day and only
missing days are computed, so a rebuild after new data is quick.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from . import dma, profiles as P
from .load import ROOT, hour_files, load_hour

DB = ROOT / "data" / "derived" / "profile_db"

# DMA "Ship type" text -> our type groups (alibi_lab.load.vessels uses ITU codes for the same groups)
DMA_GROUP = {
    "Cargo": "cargo", "Tanker": "tanker", "Passenger": "passenger", "HSC": "high speed", "Tug": "tug",
    "Towing": "tug", "Towing long/wide": "tug", "Fishing": "fishing", "Pleasure": "pleasure", "Sailing": "pleasure",
    "Pilot": "service", "SAR": "service", "Port tender": "service", "Law enforcement": "service",
    "Anti-pollution": "service", "Dredging": "service", "Diving": "service", "Medical": "service",
    "Military": "other", "Other": "other", "Reserved": "other", "Spare 1": "other", "Spare 2": "other",
    "WIG": "other", "Not party to conflict": "other",
}


# -- segments ------------------------------------------------------------------------------

def _write(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)


def segments_dk(log=print) -> int:
    """Segments for every compacted DMA day not yet done."""
    n = 0
    for f in sorted((dma.ROOT / "positions").glob("*/aisdk-*.parquet")):
        day = f.name[6:16]
        out = DB / "segments" / "dk" / f"{day}.parquet"
        if out.exists():
            continue
        pos = pd.read_parquet(f).rename(columns={"ts": "time"})
        seg = P.segments(pos).assign(source="dk", day=day)
        _write(seg, out)
        n += 1
        log(f"segments dk {day}: {len(seg)}")
    return n


def segments_fi(log=print) -> int:
    """Segments per UTC day of our own recording (complete days only; the current day is skipped)."""
    by_day: dict[str, list[Path]] = {}
    for f in hour_files():
        k = f.name[4:12]
        by_day.setdefault(f"{k[:4]}-{k[4:6]}-{k[6:8]}", []).append(f)
    n = 0
    for day, files in sorted(by_day.items()):
        out = DB / "segments" / "fi" / f"{day}.parquet"
        if out.exists() or len({f.name[4:15] for f in files}) < 24:
            continue
        loc = pd.concat([load_hour(f)[0] for f in files], ignore_index=True)
        loc = loc.drop_duplicates(["mmsi", "time", "lat", "lon"]).sort_values(["mmsi", "time"], ignore_index=True)
        seg = P.segments(loc).assign(source="fi", day=day)
        _write(seg, out)
        n += 1
        log(f"segments fi {day}: {len(seg)}")
    return n


# -- identities ----------------------------------------------------------------------------

def identities() -> pd.DataFrame:
    """One row per distinct identity seen, from both sources, with first/last date."""
    dk = duckdb.sql(f"""
        select mmsi, try_cast(imo as bigint) AS imo, name, callsign, ship_type, length,
               min(to_timestamp(first_ts))::date AS first_day, max(to_timestamp(last_ts))::date AS last_day,
               sum("rows") AS n_rows, 'dk' AS source
        from '{(dma.ROOT / "ships").as_posix()}/*/*.parquet'
        group by all""").df().rename(columns={"n_rows": "rows"})
    dk["group"] = dk["ship_type"].map(DMA_GROUP).fillna("unknown")
    metas = []
    for f in hour_files():
        m = load_hour(f)[1]
        if len(m):
            metas.append(m.assign(day=pd.to_datetime(m["rx"], unit="s").dt.date))
    meta = pd.concat(metas, ignore_index=True)
    meta["length"] = pd.to_numeric(meta["refA"], errors="coerce") + pd.to_numeric(meta["refB"], errors="coerce")
    meta["imo"] = pd.to_numeric(meta["imo"], errors="coerce").where(lambda s: s > 0)
    fi = (meta.groupby(["mmsi", "imo", "name", "callSign", "type", "length"], dropna=False)
          .agg(first_day=("day", "min"), last_day=("day", "max"), rows=("rx", "size")).reset_index()
          .rename(columns={"callSign": "callsign", "type": "ship_type"}))
    t = pd.to_numeric(fi["ship_type"], errors="coerce")
    groups = {3: "fishing/tug/special", 4: "high speed", 5: "service", 6: "passenger", 7: "cargo", 8: "tanker", 9: "other"}
    fi["group"] = (t // 10).map(groups).fillna("unknown")
    fi.loc[t.isin([30]), "group"] = "fishing"
    fi.loc[t.isin([31, 32, 52]), "group"] = "tug"
    fi.loc[t.isin([36, 37]), "group"] = "pleasure"
    fi["ship_type"] = fi["ship_type"].astype("string")
    fi["source"] = "fi"
    ids = pd.concat([dk, fi], ignore_index=True)
    for c in ("first_day", "last_day"):
        ids[c] = pd.to_datetime(ids[c].astype(str).str[:10], format="%Y-%m-%d")
    for c in ("name", "callsign", "ship_type", "group", "source"):
        ids[c] = ids[c].astype("string")
    ids["imo"] = ids["imo"].astype("Int64")
    ids.loc[(ids["imo"] < 1000000) | (ids["imo"] > 9999999), "imo"] = pd.NA  # IMO numbers have 7 digits
    ids["length"] = ids["length"].where(ids["length"] > 0)
    return ids


def vessel_keys(ids: pd.DataFrame) -> pd.DataFrame:
    """mmsi -> vessel_key, group, class, name (most-reported identity wins)."""
    best = ids.sort_values("rows", ascending=False)
    imo = best.dropna(subset=["imo"]).drop_duplicates("mmsi").set_index("mmsi")["imo"]
    kv = best.drop_duplicates("mmsi").set_index("mmsi")[["name", "group", "length"]]
    known = best[best["group"] != "unknown"].drop_duplicates("mmsi").set_index("mmsi")["group"]
    kv["group"] = known.reindex(kv.index).fillna(kv["group"])
    length = best.dropna(subset=["length"]).drop_duplicates("mmsi").set_index("mmsi")["length"]
    kv["length"] = length.reindex(kv.index)
    kv["imo"] = imo.reindex(kv.index).astype("Int64")
    kv["vessel_key"] = np.where(kv["imo"].notna(), "IMO" + kv["imo"].astype(str), "MMSI" + kv.index.astype(str))
    size = pd.Series("?", index=kv.index)
    for lo, hi, label in P.LENGTH_CLASSES:
        size[(kv["length"] >= lo) & (kv["length"] < hi)] = label
    kv["cls"] = kv["group"].astype(str) + "/" + size
    return kv.reset_index()


# -- profiles ------------------------------------------------------------------------------

def _profile_rows(segs: pd.DataFrame, by: str) -> pd.DataFrame:
    rows = []
    for source_name, s in [("all", segs), *segs.groupby("source")]:
        for key, g in s.groupby(by):
            p = P.Profile.fit(str(key), g)
            rows.append({by: key, "source": source_name, "hours": p.hours, "segments": p.segments,
                         "first_day": g["day"].min(), "last_day": g["day"].max(),
                         "draught_median": g["draught"].median() if "draught" in g else np.nan,
                         **{f: p.value.get(f) for f in P.FEATURES},
                         **{f"{f}_spread": p.spread.get(f) for f in P.FEATURES}})
    return pd.DataFrame(rows)


def build(log=print) -> dict:
    """Bring segments up to date, then rebuild identities and profiles. Returns counts."""
    new_dk, new_fi = segments_dk(log), segments_fi(log)
    ids = identities()
    keys = vessel_keys(ids)
    segs = duckdb.sql(f"select * from read_parquet('{(DB / 'segments').as_posix()}/*/*.parquet', union_by_name=true)").df()
    segs = segs.merge(keys[["mmsi", "vessel_key", "cls", "group"]], on="mmsi", how="left")
    segs["vessel_key"] = segs["vessel_key"].fillna("MMSI" + segs["mmsi"].astype(str))
    segs["cls"] = segs["cls"].fillna("unknown/?")
    vp = _profile_rows(segs, "vessel_key").merge(
        keys.drop_duplicates("vessel_key")[["vessel_key", "name", "cls", "imo"]], on="vessel_key", how="left")
    cp = _profile_rows(segs, "cls")
    DB.mkdir(parents=True, exist_ok=True)
    _write(ids, DB / "identities.parquet")
    _write(keys, DB / "vessel_keys.parquet")
    _write(vp, DB / "vessel_profiles.parquet")
    _write(cp, DB / "class_profiles.parquet")
    con = duckdb.connect(str(DB / "profiles.duckdb"))
    for name in ("identities", "vessel_keys", "vessel_profiles", "class_profiles"):
        con.execute(f"create or replace view {name} as select * from '{(DB / name).as_posix()}.parquet'")
    con.execute(f"create or replace view segments as select * from read_parquet("
                f"'{(DB / 'segments').as_posix()}/*/*.parquet', union_by_name=true)")
    con.close()
    out = {"new_dk_days": new_dk, "new_fi_days": new_fi, "segments": len(segs), "identities": len(ids),
           "vessels": int(vp.loc[vp["source"] == "all", "vessel_key"].nunique()), "classes": int(cp["cls"].nunique())}
    log(f"profile_db: {out}")
    return out
