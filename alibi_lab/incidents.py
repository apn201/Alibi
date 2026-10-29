"""Cut full-resolution AIS around known incidents out of the Danish archive.

For each case: the incident day and the day before, every Class A position within a box
around the place (all ships, so the others give the local normal). Output:
    data/external/dma_incidents/{case}/{YYYY-MM-DD}.parquet

Cases are candidates from a list compiled from press reports (Juha, 2026-10-24). Names,
IMO numbers, places and dates are not verified here; the track has to show the event.
Locations are approximate (the named place), the box is wide enough to allow for that.

The archive: from about March 2024 one zip per day; before that one zip per month holding
daily CSVs (10-35 GB a month), read member by member over HTTP ranges (remote_zip.py).
Formats differ by year: comma with header (2010) or semicolon, decimal comma, no header (2016).
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .load import ROOT
from .remote_zip import RangeFile

S3 = "http://aisdata.ais.dk.s3.eu-central-1.amazonaws.com"
OUT = ROOT / "data" / "external" / "dma_incidents"
COLS = ["ts", "mobile", "mmsi", "lat", "lon", "navstat", "rot", "sog", "cog", "heading", "imo", "callsign",
        "name", "ship_type", "cargo_type", "width", "length", "posfix", "draught", "destination", "eta", "source"]
NUM = ["lat", "lon", "rot", "sog", "cog", "heading", "width", "length", "draught"]


@dataclass(frozen=True)
class Case:
    key: str
    day: date
    vessel: str
    imo: int | None
    place: str
    lat: float
    lon: float
    dlat: float = 0.35
    dlon: float = 0.6


CASES = [
    Case("flinterforest_2010", date(2010, 8, 13), "FLINTERFOREST", 9313761, "Laröd, north of Helsingborg", 56.08, 12.64),
    Case("terry_2012", date(2012, 3, 22), "TERRY", 9169782, "Drogden, Öresund", 55.55, 12.72),
    Case("wilson_avonmouth_2012", date(2012, 10, 10), "WILSON AVONMOUTH", 9198642, "north of Helsingør", 56.07, 12.60),
    Case("simon_b_2014", date(2014, 7, 15), "SIMON B", 8511029, "Aalborg", 57.05, 9.93),
    Case("ivan_bobrov_2016", date(2016, 1, 1), "IVAN BOBROV", 7611212, "Öresund, southbound", 55.85, 12.70, 0.5, 0.6),
    Case("helsingborg_wheat_2018", date(2018, 8, 3), "", None, "Helsingborg, the Sound", 56.05, 12.68),
    Case("rix_partner_2022", date(2022, 4, 17), "RIX PARTNER", 9195212, "Great Belt", 55.35, 11.00, 0.5, 0.6),
    Case("ragna_2022", date(2022, 10, 28), "RAGNA", 9173329, "Strib, Little Belt", 55.54, 9.77),
    Case("eems_carrier_2025", date(2025, 2, 21), "EEMS CARRIER", 9148142, "Spodsbjerg, Langeland", 54.93, 10.83),
    Case("olymp_trader_2026", date(2026, 6, 8), "OLYMP TRADER", 9246906, "Korsør harbour", 55.33, 11.13),
]
# "July 2014" for Simon B has no day: 15 July is a placeholder; widen the window when reading.


def _source(day: date) -> tuple[str, str | None]:
    """(zip url, member name or None for a daily zip). Daily zips from 2024-03 on."""
    if day >= date(2024, 3, 1):
        name = f"aisdk-{day:%Y-%m-%d}.zip"
        root = f"{S3}/{name}" if day >= date(2025, 2, 27) else f"{S3}/{day:%Y}/{name}"
        return root, None
    return f"{S3}/{day:%Y}/aisdk-{day:%Y-%m}.zip", f"aisdk{day:%Y%m%d}.csv"  # matched in _open_csv


def _open_csv(day: date):
    url, member = _source(day)
    zf = zipfile.ZipFile(RangeFile(url, block=16 << 20))
    if member is None:
        info = [i for i in zf.infolist() if i.filename.endswith(".csv")][0]
    else:
        # Names vary by year: aisdk_20100813.csv, FtpRoot/ais_data/aisdk_20160101.csv, aisdk-2022-04-17.csv.
        # Match the day's digits, 8 in a row (20100813) or dashed (2022-04-17), anywhere in the name.
        ymd = re.search(r"\d{8}", member).group(0)
        dashed = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"
        info = next((i for i in zf.infolist() if ymd in i.filename or dashed in i.filename), None)
        if info is None:
            raise FileNotFoundError(f"{member} not in {url}")
    return zf.open(info)


def cut(day: date, lat: float, lon: float, dlat: float, dlon: float, chunk_rows: int = 400_000) -> pd.DataFrame:
    """All Class A rows of one day inside the box, every report kept."""
    raw = io.TextIOWrapper(_open_csv(day), encoding="utf-8", errors="replace", newline="")
    first = raw.readline()
    sep = ";" if first.count(";") > first.count(",") else ","
    header = first.lstrip().startswith("#") or "Timestamp" in first
    # Header-less files (2016): the first line is data; keep it so no report is lost.
    pending = None if header else pd.DataFrame([first.rstrip("\r\n").split(sep)[:len(COLS)]], columns=COLS)
    parts = []
    reader = pd.read_csv(raw, sep=sep, header=None, names=COLS, usecols=range(len(COLS)), dtype=str,
                         chunksize=chunk_rows, quoting=csv.QUOTE_NONE, on_bad_lines="skip", engine="c")
    for chunk in reader:
        if pending is not None:
            chunk = pd.concat([pending, chunk], ignore_index=True)
            pending = None
        chunk = chunk[chunk["mobile"] == "Class A"]
        for c in NUM:
            chunk[c] = pd.to_numeric(chunk[c].str.replace(",", ".", regex=False), errors="coerce")
        box = chunk[chunk["lat"].between(lat - dlat, lat + dlat) & chunk["lon"].between(lon - dlon, lon + dlon)]
        if len(box):
            parts.append(box)
    df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=COLS)
    df["ts"] = pd.to_datetime(df["ts"], format="%d/%m/%Y %H:%M:%S", errors="coerce", utc=True)
    df["mmsi"] = pd.to_numeric(df["mmsi"], errors="coerce").astype("Int64")
    for c in ("imo", "name", "callsign", "ship_type", "destination", "navstat"):
        df[c] = df[c].where(~df[c].isin(["Unknown", "Undefined", "Unknown value", ""]))
    return df


def fetch(case: Case, days_before: int = 1, days_after: int = 0, log=print) -> list[Path]:
    out = []
    for d in range(-days_before, days_after + 1):
        day = case.day + timedelta(days=d)
        p = OUT / case.key / f"{day.isoformat()}.parquet"
        if p.exists():
            out.append(p)
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        df = cut(day, case.lat, case.lon, case.dlat, case.dlon)
        df.to_parquet(p, index=False)
        log(f"{case.key} {day}: {len(df):,} rows, {df['mmsi'].nunique()} ships")
        out.append(p)
    return out
