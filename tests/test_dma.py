import zipfile

import pandas as pd

from alibi_lab import dma

HEADER = ("# Timestamp,Type of mobile,MMSI,Latitude,Longitude,Navigational status,ROT,SOG,COG,Heading,IMO,"
          "Callsign,Name,Ship type,Cargo type,Width,Length,Type of position fixing device,Draught,Destination,"
          "ETA,Data source type,A,B,C,D\n")


def row(t, mobile, mmsi, lat, lon, sog, imo="Unknown", name="", stype="Undefined", length=""):
    return (f"{t},{mobile},{mmsi},{lat},{lon},Under way using engine,0.0,{sog},90.0,90,{imo},Unknown,{name},"
            f"{stype},,20,{length},GPS,7.5,GDANSK,,AIS,100,20,10,10\n")


def make_day(tmp_path):
    lines = [HEADER]
    for s in range(0, 180, 10):  # ship 1: every 10 s for 3 minutes
        lines.append(row(f"08/10/2026 00:{s // 60:02d}:{s % 60:02d}", "Class A", 111111111, 55.0, 12.0 + s / 1e4,
                         12.0, "9000001", "ALPHA", "Cargo", "120"))
    lines.append(row("08/10/2026 00:00:05", "Class B", 222222222, 55.1, 12.1, 5.0))  # not Class A: dropped
    lines.append(row("08/10/2026 00:00:07", "Base Station", 2190001, 55.2, 12.2, 0.0))
    lines.append(row("08/10/2026 00:00:09", "Class A", 333333333, 91.0, 181.0, 0.0))  # no position: dropped
    lines.append(row("08/10/2026 00:01:00", "Class A", 111111111, 55.0, 12.01, 12.0, "9000001", "ALPHA-RENAMED",
                     "Cargo", "120"))
    z = tmp_path / "aisdk-2026-10-08.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("aisdk-2026-10-08.csv", "".join(lines))
    return z


def test_ingest_keeps_class_a_one_row_per_minute_and_identities(tmp_path):
    entry = dma.ingest(make_day(tmp_path), out_root=tmp_path / "out")
    pos = pd.read_parquet(tmp_path / "out" / "positions" / "2026" / "aisdk-2026-10-08.parquet")
    ships = pd.read_parquet(tmp_path / "out" / "ships" / "2026" / "aisdk-2026-10-08.parquet")
    assert set(pos["mmsi"]) == {111111111}
    assert len(pos) == 3  # minutes 0, 1, 2
    assert pos["ts"].iloc[0] == int(pd.Timestamp("2026-10-08", tz="UTC").timestamp())
    assert sorted(ships["name"].dropna()) == ["ALPHA", "ALPHA-RENAMED"]  # identity change is kept
    assert entry["ships"] == 1 and entry["positions"] == 3
    assert dma.done_days(tmp_path / "out") == {"2026-10-08"}
