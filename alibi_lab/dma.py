"""Danish Maritime Authority AIS archive -> compact, queryable Parquet. Raw is not kept.

Source: http://aisdata.ais.dk/  daily `aisdk-YYYY-MM-DD.zip` (~600 MB zip, ~3 GB CSV,
~15 M Class A rows, ~2,500 ships). Coverage (measured on 2026-10-08): Skagerrak,
Kattegat, the Danish straits and the western/southern Baltic to about 18.5 E.
Most ships entering or leaving the Baltic pass here, so it gives ships we later see
in the Gulf of Finland a history.

Per day, one streaming pass keeps:
    positions/YYYY/aisdk-YYYY-MM-DD.parquet   Class A, one row per ship per minute
        ts (epoch s, UTC), mmsi, lat, lon, sog, cog, heading, rot, navstat, draught
    ships/YYYY/aisdk-YYYY-MM-DD.parquet       one row per ship and identity seen that day
        mmsi, imo, name, callsign, ship_type, cargo_type, length, width, a, b, c, d,
        draught_min, draught_max, destination, first_ts, last_ts, rows
    manifest.jsonl                            what was ingested, sizes, row counts
The zip is deleted afterwards unless keep_raw (incident days: fingerprints need every row).

Query with DuckDB, e.g.
    duckdb.sql("select mmsi, count(*) from 'F:/alibi-data/dma/positions/*/*.parquet' group by 1")
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

BASE_URL = "http://aisdata.ais.dk"
ROOT = Path(r"F:\alibi-data\dma")  # outside Dropbox: big, and regenerable from the source
RESAMPLE_S = 60
USER_AGENT = "apn201/alibi-lab 0.1"

COLUMNS = {
    "# Timestamp": "ts", "Type of mobile": "mobile", "MMSI": "mmsi", "Latitude": "lat", "Longitude": "lon",
    "Navigational status": "navstat", "ROT": "rot", "SOG": "sog", "COG": "cog", "Heading": "heading",
    "IMO": "imo", "Callsign": "callsign", "Name": "name", "Ship type": "ship_type", "Cargo type": "cargo_type",
    "Width": "width", "Length": "length", "Draught": "draught", "Destination": "destination",
    "A": "a", "B": "b", "C": "c", "D": "d",
}
NUMERIC = ["lat", "lon", "rot", "sog", "cog", "heading", "width", "length", "draught", "a", "b", "c", "d"]
IDENTITY = ["mmsi", "imo", "name", "callsign", "ship_type", "cargo_type", "length", "width", "a", "b", "c", "d"]


def zip_name(day: date) -> str:
    return f"aisdk-{day:%Y-%m-%d}.zip"


def download(day: date, raw_dir: Path | None = None) -> Path:
    raw_dir = raw_dir or ROOT / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / zip_name(day)
    if dest.exists() and zipfile.is_zipfile(dest):
        return dest
    tmp = dest.with_suffix(".part")
    # Recent days sit at the root; older ones in a year folder (2024/aisdk-2024-11-16.zip).
    # Before March 2024 some months are single monthly zips (~17 GB) - not handled here.
    last_exc = None
    for url in (f"{BASE_URL}/{zip_name(day)}", f"{BASE_URL}/{day:%Y}/{zip_name(day)}"):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=600) as resp, open(tmp, "wb") as fh:
                while chunk := resp.read(1 << 22):
                    fh.write(chunk)
            break
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            last_exc = exc
    else:
        raise last_exc
    if not zipfile.is_zipfile(tmp):
        tmp.unlink()
        raise IOError(f"{zip_name(day)}: download is not a valid zip")
    tmp.replace(dest)
    return dest


def _batches(zip_path: Path):
    z = zipfile.ZipFile(zip_path)
    inner = [i for i in z.infolist() if i.filename.endswith(".csv")][0]
    # Memory: numbers are parsed as numbers by Arrow (not text first), "Unknown"/"Undefined"
    # become nulls while reading, non-Class-A rows are dropped before pandas sees them, and
    # blocks are small. Peak per process ~1/3 of the first version (measured 2026-10-21).
    typed = {"MMSI": pa.int64(), "# Timestamp": pa.timestamp("s")}
    typed.update({src: pa.float64() for src, dst in COLUMNS.items() if dst in NUMERIC})
    nulls = ["", "Unknown", "Undefined"]
    convert = pacsv.ConvertOptions(include_columns=list(COLUMNS), column_types=typed, null_values=nulls,
                                   strings_can_be_null=True, timestamp_parsers=["%d/%m/%Y %H:%M:%S"])
    reader = pacsv.open_csv(z.open(inner), read_options=pacsv.ReadOptions(block_size=16 << 20),
                            convert_options=convert)
    for batch in reader:
        batch = batch.filter(pc.equal(batch.column("Type of mobile"), "Class A"))
        if batch.num_rows == 0:
            continue
        df = batch.to_pandas().rename(columns=COLUMNS)
        df["ts"] = (df["ts"] - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1)  # naive UTC -> epoch s
        df = df[df["lat"].between(-90, 90) & df["lon"].between(-180, 180) & (df["mmsi"] > 0)]
        yield df


def ingest(zip_path: Path, out_root: Path | None = None) -> dict:
    """One day zip -> positions + ships Parquet. Returns the manifest entry."""
    out_root = out_root or ROOT
    day = datetime.strptime(zip_path.name, "aisdk-%Y-%m-%d.zip").date()
    t0 = time.time()
    kept, ids, rows_in = [], [], 0
    for df in _batches(zip_path):
        rows_in += len(df)
        df = df.assign(bucket=df["ts"] // RESAMPLE_S)
        kept.append(df.drop_duplicates(["mmsi", "bucket"])[
            ["ts", "mmsi", "lat", "lon", "sog", "cog", "heading", "rot", "navstat", "draught", "bucket"]])
        g = df.groupby(IDENTITY, dropna=False)
        ids.append(g.agg(draught_min=("draught", "min"), draught_max=("draught", "max"),
                         destination=("destination", "last"), first_ts=("ts", "min"), last_ts=("ts", "max"),
                         rows=("ts", "size")).reset_index())
    pos = pd.concat(kept, ignore_index=True).sort_values(["mmsi", "ts"])
    pos = pos.drop_duplicates(["mmsi", "bucket"]).drop(columns="bucket").reset_index(drop=True)
    pos["navstat"] = pos["navstat"].astype("category")
    for c in ["lat", "lon"]:
        pos[c] = pos[c].astype("float64")
    for c in ["sog", "cog", "heading", "rot", "draught"]:
        pos[c] = pos[c].astype("float32")
    ships = (pd.concat(ids, ignore_index=True).groupby(IDENTITY, dropna=False)
             .agg(draught_min=("draught_min", "min"), draught_max=("draught_max", "max"),
                  destination=("destination", "last"), first_ts=("first_ts", "min"), last_ts=("last_ts", "max"),
                  rows=("rows", "sum")).reset_index())
    # identity rows with no static data at all are just position-only reports: fold them away
    static = ships[IDENTITY[1:]].notna().any(axis=1)
    ships = pd.concat([ships[static], ships[~static & ~ships["mmsi"].isin(ships.loc[static, "mmsi"])]])

    paths = {}
    for kind, frame in (("positions", pos), ("ships", ships)):
        p = out_root / kind / f"{day:%Y}" / zip_path.name.replace(".zip", ".parquet")
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".part")
        pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), tmp, compression="zstd")
        tmp.replace(p)
        paths[kind] = p
    entry = {"day": day.isoformat(), "zip_bytes": zip_path.stat().st_size, "class_a_rows": rows_in,
             "positions": len(pos), "ships": int(pos["mmsi"].nunique()),
             "positions_bytes": paths["positions"].stat().st_size, "ships_bytes": paths["ships"].stat().st_size,
             "seconds": round(time.time() - t0, 1),
             "ingested": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with open(out_root / "manifest.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    return entry


def done_days(out_root: Path | None = None) -> set[str]:
    out_root = out_root or ROOT
    return {p.name[6:16] for p in (out_root / "positions").glob("*/aisdk-*.parquet")}


def run(days: list[date], keep_raw: set[date] = frozenset(), log=print) -> None:
    """Download -> ingest -> delete zip, day by day. Skips days already ingested."""
    done = done_days()
    for day in days:
        if day.isoformat() in done:
            continue
        try:
            z = download(day)
            e = ingest(z)
            if day not in keep_raw:
                z.unlink()
            log(f"{day}  {e['class_a_rows'] / 1e6:5.1f} M rows -> {e['positions'] / 1e6:4.2f} M positions, "
                f"{e['ships']:,} ships, {e['positions_bytes'] / 1e6:5.1f} MB  ({e['seconds']:.0f} s)")
        except Exception as exc:  # one bad day must not stop the run; it is retried next time
            log(f"{day}  FAILED {exc!r}")
