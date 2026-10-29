"""Third-party tracks of real incidents, read into the same shape as load.load()'s locations.

These files are NOT ours to publish: they live in data/external/ (git-ignored) and are
fetched from their source. Keep only the reader here.

Eagle S (Christmas 2024, Estlink 2): eagles-report.com, `eagle_s_voyage_ais.csv`.
Three header rows; Finnish number format (decimal comma); `dd.mm.yyyy HH:MM:SS` in UTC.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .load import ROOT, SENTINELS

EXTERNAL = ROOT / "data" / "external"
EAGLE_S_CSV = EXTERNAL / "eagle_s" / "eagle_s_voyage_ais.csv"

# Ground truth from the Eagle S technical report v4 (eagles-report.com), UTC, 25.12.2024.
EAGLE_S_EVENTS = {
    "departed Ust-Luga": "2024-12-25 01:00:00",
    "speed starts to drop (anchor dragging)": "2024-12-25 10:13:04",
    "Estlink 2 crossed, offline": "2024-12-25 10:26:00",
    "last cable/pipeline crossing": "2024-12-25 10:50:50",
    "main engine rpm drops": "2024-12-25 11:04:59",
    "engine stopped, drifting": "2024-12-25 11:49:00",
}


def eagle_s(path: Path = EAGLE_S_CSV) -> pd.DataFrame:
    raw = pd.read_csv(path, skiprows=[0, 2], decimal=",", dtype=str)
    num = lambda c: pd.to_numeric(raw[c].str.replace(",", ".", regex=False), errors="coerce")
    ts = pd.to_datetime(raw["Date and UTC Time"], format="%d.%m.%Y %H:%M:%S", utc=True)
    df = pd.DataFrame({
        "mmsi": pd.to_numeric(raw["MMSI"], errors="coerce").astype("Int64"),
        "time": ((ts - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(seconds=1)).astype("int64"),
        "lat": num("Latitude"), "lon": num("Longitude"), "sog": num("SOG"),
        "cog": num("COG"), "heading": num("HDG"), "rot": num("ROT"),
        "status": raw["Status"], "name": raw["Name"],
        "length": num("Length Overall"), "draught": num("Draught"),
    })
    for c in ("sog", "cog", "heading", "rot"):
        df.loc[df[c] == SENTINELS[c], c] = np.nan
    df.loc[df["cog"] >= 360, "cog"] = np.nan
    df["ts"] = pd.to_datetime(df["time"], unit="s", utc=True)
    return df.sort_values("time", ignore_index=True)


def events_epoch(events: dict[str, str] = EAGLE_S_EVENTS) -> dict[str, int]:
    return {k: int(pd.Timestamp(v, tz="UTC").timestamp()) for k, v in events.items()}
