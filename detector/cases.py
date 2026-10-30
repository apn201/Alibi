"""Build replay cases: run the rules over recorded tracks and write AssessmentRequests.

`python -m detector cases [--only id,id] [--no-counts]` writes data/cases/<case_id>.json (format in
docs/BUILD.md, "Case files"), data/cases/index.json and data/cases/detector_counts.csv.

Why one superset per case: a case file holds the candidates of the MOST sensitive tier (s=1),
each tagged baseline_summary["min_tier"] (0/1/2 = lowest tier at which the same rule also fires).
The replay then picks the candidates for any sensitivity by filtering, and the detector alone is
always compared with ALIBI on exactly the same events.

Sources (all read-only):
  fi   our Digitraffic recording, Gulf of Finland, via alibi_lab.load (hour files, raw reports)
  dk   Danish AIS archive (F:/alibi-data/dma), one report per ship per minute
  Eagle S / TERRY: third-party and open-data cut-outs under data/external. Everything written here
  sits under data/ (git-ignored); the Eagle S case file must never be committed.

Fleet cases use merchant ships only (cargo, tanker, passenger, > 50 m): working vessels are not scored
by ALIBI, so listing them as candidates would only add noise. The recorder's own outages (ledger
gaps-*.jsonl plus fleet-wide silences in the data) are handed to the ais_gap rule so a dead
recorder is not reported as a dark ship.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import rules
from rules._core import iso

ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = ROOT / "data" / "cases"
PROFILE_DB = ROOT / "data" / "derived" / "profile_db"
SNAPSHOT_PROFILE_DB = ROOT / "snapshot" / "derived" / "profile_db"  # a plain git clone has only this
DMA_POSITIONS = Path("F:/alibi-data/dma/positions")
DMA_SHIPS = Path("F:/alibi-data/dma/ships")
MAX_BYTES = None  # set by --out: keep each case file under this (committed snapshots)
TRACK_H = 6.0  # hours of track before the event end
AFTER_MIN = 30  # minutes of track after the event end
LOOKBACK_H = 7  # context loaded before a window: 6 h track + the rules' reference hour
MERCHANT = {"cargo", "tanker", "passenger"}
TIER_SENS = {0: 0.0, 1: 0.5, 2: 1.0}
REPLAY_DAYS = ["2026-10-25", "2026-10-26", "2026-10-27", "2026-10-28"]
COUNT_DAYS = [d.strftime("%Y-%m-%d") for d in pd.date_range("2026-10-05", "2026-10-28")]

CASES = {
    "eagle_s_2024": dict(title="Eagle S, 25 Dec 2024: speed drop towards Estlink 2", kind="known_case", region="gof",
                         start="2024-12-25T01:00:00Z", end="2024-12-25T13:00:00Z", third_party=True),
    "fi_fleet_2026_10_05": dict(title="Gulf of Finland fleet slowdown, 5-6 Oct 2026", kind="fleet_slowdown",
                                region="gof", src="fi", start="2026-10-05T18:00:00Z", end="2026-10-06T18:00:00Z",
                                third_party=False, cap=None),
    "dk_oct2025": dict(title="Danish waters fleet slowdown, 3-6 Oct 2025 (widest)", kind="fleet_slowdown", region="dk",
                       src="dk", start="2025-10-03T07:00:00Z", end="2025-10-06T06:00:00Z", third_party=False, cap=60),
    "dk_jul2026": dict(title="Danish waters fleet slowdown, 2-4 Jul 2026 (counter-example)", kind="counter_example",
                       region="dk", src="dk", start="2026-07-02T14:00:00Z", end="2026-07-04T01:00:00Z",
                       third_party=False, cap=60),
    "dk_feb2026": dict(title="Danish waters fleet slowdown, 1-7 Feb 2026", kind="fleet_slowdown", region="dk", src="dk",
                       start="2026-02-01T17:00:00Z", end="2026-02-07T10:00:00Z", third_party=False, cap=60),
    "terry_2012": dict(title="TERRY, Oresund, 22 Mar 2012: grounding pattern", kind="known_case", region="dk",
                       start="2012-03-22T07:00:00Z", end="2012-03-22T13:00:00Z", third_party=False),
}
for _d in REPLAY_DAYS:
    CASES[f"fi_replay_{_d}"] = dict(title=f"Recorded day {_d}: every candidate", kind="replay_day", region="gof",
                                    src="fi", start=f"{_d}T00:00:00Z", end=f"{_d}T23:59:59Z", third_party=False, cap=200)


def _epoch(s: str) -> float:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


# ---------------------------------------------------------------- vessels and outages

_VK = None


def vessel_keys() -> pd.DataFrame:
    global _VK
    if _VK is None:
        path = PROFILE_DB / "vessel_keys.parquet"
        v = pd.read_parquet(path if path.exists() else SNAPSHOT_PROFILE_DB / "vessel_keys.parquet")
        _VK = v.astype({"mmsi": "int64", "name": object, "group": object, "length": "float64"}).drop_duplicates("mmsi").set_index("mmsi")
    return _VK


def vessel_meta(mmsi: int, case_id: str, extra: dict | None = None) -> dict:
    vk = vessel_keys()
    row = vk.loc[mmsi] if mmsi in vk.index else None
    meta = {"case_id": case_id, "mmsi": int(mmsi), "vessel_name": None, "ship_type": None, "length_m": None, "imo": None}
    if row is not None:
        meta.update(vessel_name=None if pd.isna(row["name"]) else str(row["name"]).replace("_", " "),
                    ship_type=None if pd.isna(row["group"]) or row["group"] == "unknown" else str(row["group"]),
                    length_m=None if pd.isna(row["length"]) else float(row["length"]),
                    imo=None if pd.isna(row["imo"]) else int(row["imo"]))
    meta.update({k: v for k, v in (extra or {}).items() if v is not None})
    return meta


def ledger_outages(ais_dir: Path | None = None, pad_s: float = 60.0) -> list[tuple[float, float]]:
    """Recorder outages from <ais_dir or data/ais>/gaps*.jsonl: from each disconnect/stop to the next resume,
    and for every resume that reports a silence, that silence."""
    out = []
    for path in sorted(Path(ais_dir or ROOT / "data" / "ais").glob("gaps*.jsonl")):
        open_at = None
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            ev, ts = e.get("event"), float(e["ts"])
            if ev in ("disconnect", "stop") and open_at is None:
                open_at = ts
            elif ev == "resume":
                if open_at is not None:
                    out.append((open_at - pad_s, ts + pad_s))
                    open_at = None
                else:
                    import re
                    m = re.search(r"silence ([\d.]+) s", e.get("detail", ""))
                    if m:
                        out.append((ts - float(m.group(1)) - pad_s, ts + pad_s))
        if open_at is not None:
            out.append((open_at - pad_s, float("inf")))
    return out


def silence_outages(minute_counts: pd.Series, min_len: int = 3) -> list[tuple[float, float]]:
    """Fleet-wide silences in the data itself: runs of >= min_len minutes with under 10 % of the usual
    message count. Catches outages the ledger did not see (the feed up but silent)."""
    idx = np.arange(minute_counts.index.min(), minute_counts.index.max() + 1)
    c = minute_counts.reindex(idx, fill_value=0).to_numpy()
    low = c < 0.1 * np.median(c[c > 0]) if (c > 0).any() else np.ones(len(c), bool)
    from rules._core import runs
    return [(float(idx[a] * 60 - 60), float(idx[b] * 60 + 120)) for a, b in runs(low) if b - a + 1 >= min_len]


# ---------------------------------------------------------------- loading fleets as 1-minute tracks

def _bin_minutes(df: pd.DataFrame) -> pd.DataFrame:
    """One row per ship per minute (median speed/position, last course/heading)."""
    df = df.assign(m=(df["time"] // 60).astype("int64"))
    g = df.groupby(["mmsi", "m"], sort=True).agg(lat=("lat", "median"), lon=("lon", "median"), sog=("sog", "median"),
                                                  cog=("cog", "last"), heading=("heading", "last")).reset_index()
    g["time"] = g["m"] * 60
    return g.drop(columns="m")


def merchant_minutes(loc: pd.DataFrame, meta: pd.DataFrame, s: float, e: float, ais_dir: Path | None = None):
    """Raw locations + metadata of our recording -> merchant ships binned to minutes, plus recorder outages."""
    from alibi_lab.load import vessels
    loc = loc[(loc["time"] >= s) & (loc["time"] <= e)]
    outages = ledger_outages(ais_dir) + silence_outages((loc["time"] // 60).value_counts())
    v = vessels(meta)
    length = pd.to_numeric(v.get("refA"), errors="coerce") + pd.to_numeric(v.get("refB"), errors="coerce")
    ids = set(v.index[v["group"].isin(MERCHANT) & (length > 50)])
    vk = vessel_keys()
    ids |= set(vk.index[vk["group"].isin(MERCHANT) & (vk["length"] > 50)])
    loc = loc[loc["mmsi"].isin(ids)]
    return _bin_minutes(loc[["mmsi", "time", "lat", "lon", "sog", "cog", "heading"]]), outages


def load_fi(start: str, end: str) -> tuple[pd.DataFrame, list]:
    """Merchant ships of our recording between two ISO times, binned to minutes, plus recorder outages."""
    from alibi_lab.load import load
    s, e = _epoch(start), _epoch(end)
    h = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y%m%d-%H")
    loc, meta = load(h(s), h(e))
    return merchant_minutes(loc, meta, s, e)


def load_dk(start: str, end: str) -> tuple[pd.DataFrame, list]:
    import duckdb
    s, e = int(_epoch(start)), int(_epoch(end))
    days = pd.date_range(datetime.fromtimestamp(s, timezone.utc).date(), datetime.fromtimestamp(e, timezone.utc).date())
    pos = [str(DMA_POSITIONS / f"{d:%Y}" / f"aisdk-{d:%Y-%m-%d}.parquet") for d in days]
    ships = [str(DMA_SHIPS / f"{d:%Y}" / f"aisdk-{d:%Y-%m-%d}.parquet") for d in days]
    pos = [p for p in pos if Path(p).exists()]
    ships = [p for p in ships if Path(p).exists()]
    con = duckdb.connect()
    ids = set(con.sql(f"select distinct mmsi from read_parquet({ships!r}) where ship_type in ('Cargo','Tanker','Passenger') "
                      f"and length > 50").df()["mmsi"].astype("int64"))
    vk = vessel_keys()
    ids |= set(vk.index[vk["group"].isin(MERCHANT) & (vk["length"] > 50)])
    con.register("ids", pd.DataFrame({"mmsi": sorted(ids)}))
    df = con.sql(f"select ts as time, mmsi, lat, lon, sog, cog, heading from read_parquet({pos!r}) "
                 f"where ts between {s} and {e} and mmsi in (select mmsi from ids)").df()
    df = df.astype({"mmsi": "int64", "time": "int64"})
    return df.sort_values(["mmsi", "time"], ignore_index=True), []  # the archive has no recorder ledger


# ---------------------------------------------------------------- candidates, ranking, requests

def significance(e: dict) -> float:
    """Rough 'how much' for ranking when a case is capped; comparable across event types."""
    b = e["baseline_summary"]
    bonus = 2.0 * (2 - b.get("min_tier", 2))  # events the conservative tiers also fire on rank first
    return bonus + _raw_significance(e)


def _raw_significance(e: dict) -> float:
    b = e["baseline_summary"]
    dur = (rules._core._t(e["end_time"]) - rules._core._t(e["start_time"])) / 60
    if e["event_type"] == "slowdown":
        return b.get("drop_pct", 0) / 100 * min(dur, 180) / 10 + 1
    if e["event_type"] == "grounding_pattern":
        return 3.0 + (3.0 if b.get("erratic_before") else 0.0)  # berthing ferries fire it too: not top-ranked by default
    if e["event_type"] == "ais_gap":
        return min(b.get("gap_min", 0) / 60, 2.0)
    return b.get("minutes_inside", 0) / 30


def fleet_candidates(tracks: pd.DataFrame, outages, lo: float, hi: float) -> list[tuple[dict, int]]:
    """Run all tiers over every ship; keep events that start inside [lo, hi). Returns (event, mmsi)."""
    found = []
    stops = rules.learn_stop_areas(tracks)  # berths and anchorages other ships use, from this window's traffic
    for mmsi, g in tracks.groupby("mmsi", sort=False):
        if len(g) < 30:
            continue
        evs = [e for e in rules.detect_tiers(g, mmsi=int(mmsi), outages=outages or None, stops=stops)
               if lo <= rules._core._t(e["start_time"]) < hi]
        found += [(e, int(mmsi)) for e in merge_overlaps(evs)]
    return found


def merge_overlaps(evs: list[dict]) -> list[dict]:
    """One ship, one episode, one candidate: of events that overlap in time (a slowdown inside a corridor
    loiter, say) keep the most significant; the others are listed in its baseline_summary["also"]."""
    t = rules._core._t
    groups: list[list[dict]] = []
    for e in sorted(evs, key=lambda e: t(e["start_time"])):
        if groups and t(e["start_time"]) <= max(t(o["end_time"]) for o in groups[-1]):
            groups[-1].append(e)
        else:
            groups.append([e])
    out = []
    for grp in groups:
        keep = max(grp, key=significance)
        others = [o for o in grp if o is not keep]
        if others:
            keep["baseline_summary"]["also"] = [{"event_type": o["event_type"], "start_time": o["start_time"],
                                                 "end_time": o["end_time"]} for o in others]
            keep["baseline_summary"]["min_tier"] = min(o["baseline_summary"].get("min_tier", 2) for o in grp)
        out.append(keep)
    return out


def build_request(frame: pd.DataFrame, e: dict, meta: dict) -> dict:
    end = rules._core._t(e["end_time"]) + AFTER_MIN * 60
    w = frame[(frame["time"] >= end - TRACK_H * 3600) & (frame["time"] <= end)]
    ts = pd.to_datetime(w["time"], unit="s", utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    track = []
    for t, la, lo, sog, cog, hd in zip(ts, w["lat"], w["lon"], w["sog"], w["cog"], w["heading"]):
        o = {"timestamp": t, "latitude": round(float(la), 5), "longitude": round(float(lo), 5)}
        if not np.isnan(sog):
            o["sog_knots"] = round(float(sog), 1)
        if not np.isnan(cog) and cog < 360:
            o["cog_degrees"] = round(float(cog), 1)
        if not np.isnan(hd) and hd < 360:
            o["heading_degrees"] = round(float(hd), 0)
        track.append(o)
    ev = {**e, "baseline_summary": {**e["baseline_summary"], "detector": "alibi-demo-detector rules"}}
    return {"event": ev, "track": track, "metadata": meta}


def atomic_write(path: Path, text: str) -> None:
    """Write beside, then replace: a reader (the GUI) never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def update_index(row: dict) -> None:
    """Insert/replace one case in index.json (live first, then the declared order, then anything else)."""
    p = CASES_DIR / "index.json"
    cases = {}
    if p.exists():
        cases = {c["case_id"]: c for c in json.loads(p.read_text(encoding="utf-8"))["cases"]}
    cases[row["case_id"]] = row
    order = ["live_gof"] + list(CASES)
    ids = [c for c in order if c in cases] + [c for c in cases if c not in order]
    atomic_write(p, json.dumps({"cases": [cases[c] for c in ids]}, indent=1))


def write_case(case_id: str, spec: dict, found: list[tuple[dict, int]], tracks: pd.DataFrame, extra_meta=None,
               notes: dict | None = None) -> dict:
    """Rank, cap, build requests and write data/cases/<case_id>.json. Returns the index row."""
    found = sorted(found, key=lambda f: -significance(f[0]))
    total = len(found)
    cap = spec.get("cap")
    kept = found if not cap else found[:cap]
    by_ship = {m: g for m, g in tracks[tracks["mmsi"].isin({m for _, m in kept})].groupby("mmsi")}
    kept = sorted(kept, key=lambda f: -significance(f[0]))  # most significant first, for trimming
    reqs = []
    for e, m in kept:
        meta = vessel_meta(m, case_id, (extra_meta or {}).get(m))
        meta["min_tier"] = e["baseline_summary"].get("min_tier", 2)
        meta["min_sensitivity"] = TIER_SENS[meta["min_tier"]]
        reqs.append(build_request(by_ship[m], e, meta))
    while True:
        ordered = sorted(reqs, key=lambda r: r["event"]["start_time"])
        doc = {"case_id": case_id, "title": spec["title"], "kind": spec["kind"], "region": spec["region"],
               "start": spec["start"], "end": spec["end"], "third_party": spec["third_party"],
               "candidates_total": total, "candidates_kept": len(ordered), "requests": ordered}
        if notes:
            doc["notes"] = notes
        text = json.dumps(doc, separators=(",", ":"))
        if MAX_BYTES is None or len(text) <= MAX_BYTES or len(reqs) <= 1:
            break
        reqs = reqs[: max(1, int(len(reqs) * MAX_BYTES / len(text) * 0.95))]  # keep the most significant
    reqs = ordered
    atomic_write(CASES_DIR / f"{case_id}.json", text)
    path = CASES_DIR / f"{case_id}.json"
    types = pd.Series([r["event"]["event_type"] for r in reqs]).value_counts().to_dict()
    tiers = pd.Series([r["metadata"]["min_tier"] for r in reqs]).value_counts().to_dict()
    return {"case_id": case_id, "title": spec["title"], "kind": spec["kind"], "region": spec["region"],
            "start": spec["start"], "end": spec["end"], "third_party": spec["third_party"],
            "candidates_total": total, "candidates_kept": len(reqs), "by_type": types,
            "by_min_tier": {str(k): int(v) for k, v in tiers.items()}, "file": f"{case_id}.json",
            "bytes": path.stat().st_size}


# ---------------------------------------------------------------- the special cases

def eagle_case() -> tuple[dict, dict]:
    from alibi_lab.external import eagle_s, events_epoch
    ev = events_epoch()
    onset = ev["speed starts to drop (anchor dragging)"]
    e = eagle_s()
    e = e[(e["time"] >= ev["departed Ust-Luga"]) & (e["time"] <= ev["engine stopped, drifting"] + 3600)]
    mmsi = int(e["mmsi"].iloc[0])
    track = _bin_minutes(e[["mmsi", "time", "lat", "lon", "sog", "cog", "heading"]].assign(mmsi=mmsi))
    flags = {}
    for s in (0.0, 0.5, 1.0):
        sd = [x for x in rules.detect(e, s, mmsi=mmsi) if x["event_type"] == "slowdown"]
        if sd:
            at = rules._core._t(sd[0]["baseline_summary"]["detected_at"])
            flags[str(s)] = round((at - onset) / 60, 1)
        else:
            flags[str(s)] = None
    found = [(x, mmsi) for x in rules.detect_tiers(e, mmsi=mmsi)]
    # the Eagle S file carries its own name/length/IMO; vessel_keys has it as EAGLE_S, group unknown
    extra = {mmsi: {"ship_type": "tanker", "vessel_name": "EAGLE S"}}
    notes = {"minutes_after_onset_flagged": flags, "onset_utc": "2024-12-25T10:13:04Z",
             "source": "eagles-report.com voyage AIS; third-party data, not for publication"}
    return dict(found=found, tracks=track, extra=extra, notes=notes), flags


def terry_case():
    d = ROOT / "data" / "external" / "dma_incidents" / "terry_2012"
    t = pd.concat([pd.read_parquet(p) for p in sorted(d.glob("*.parquet"))])
    t = t[t["mmsi"] == 256065000].copy()
    t["time"] = t["ts"].map(lambda x: int(x.timestamp()))
    t = t.sort_values("time")
    track = _bin_minutes(t[["mmsi", "time", "lat", "lon", "sog", "cog", "heading"]].assign(mmsi=256065000))
    found = [(x, 256065000) for x in rules.detect_tiers(track, mmsi=256065000)]
    extra = {256065000: {"vessel_name": "TERRY", "ship_type": "tanker", "length_m": 146.0, "imo": 9169782}}
    return dict(found=found, tracks=track, extra=extra, notes={"source": "Danish Maritime Authority open AIS, 22 Mar 2012"})


# ---------------------------------------------------------------- driver

def run_window(spec: dict):
    src = spec["src"]
    lo, hi = _epoch(spec["start"]), _epoch(spec["end"])
    ls = iso(lo - LOOKBACK_H * 3600)
    le = iso(hi + AFTER_MIN * 60 + 3600)
    tracks, outages = (load_fi if src == "fi" else load_dk)(ls, le)
    return tracks, fleet_candidates(tracks, outages, lo, hi), outages


def counts_for_day(day: str) -> tuple[dict, tuple | None]:
    spec = dict(CASES.get(f"fi_replay_{day}", dict(title=f"Recorded day {day}: every candidate", kind="replay_day",
                                                      region="gof", src="fi", third_party=False, cap=200)),
                start=f"{day}T00:00:00Z", end=f"{day}T23:59:59Z", src="fi")
    tracks, found, _ = run_window(spec)
    tiers = np.array([e["baseline_summary"]["min_tier"] for e, _ in found], int)
    row = {"date": day, "ships": int(tracks["mmsi"].nunique()),
           **{f"s={TIER_SENS[t]}": int((tiers <= t).sum()) for t in (0, 1, 2)}}
    for typ in ("slowdown", "grounding_pattern", "ais_gap", "corridor_loiter"):
        row[f"s=0.5 {typ}"] = sum(1 for (e, _), t in zip(found, tiers) if t <= 1 and e["event_type"] == typ)
    return row, (spec, found, tracks)


def main(argv=None) -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m detector cases")
    ap.add_argument("--only", help="comma-separated case ids (default: all)")
    ap.add_argument("--no-counts", action="store_true", help="skip data/cases/detector_counts.csv")
    ap.add_argument("--out", help="write here instead of data/cases (a committed snapshot): third-party cases are "
                    "skipped, files are kept under 14 MB, no counts file")
    a = ap.parse_args(argv)
    global CASES_DIR, MAX_BYTES
    want = set(a.only.split(",")) if a.only else None
    if a.out:
        CASES_DIR, MAX_BYTES = Path(a.out).resolve(), 14_000_000
        a.no_counts = True
        skipped = [c for c, sp in CASES.items() if sp["third_party"]]
        want = (want or set(CASES)) - set(skipped)
        print("snapshot mode, skipping third-party cases:", ", ".join(skipped))
    CASES_DIR.mkdir(parents=True, exist_ok=True)

    def save(row):
        update_index(row)
        print(f"  {row['case_id']}: {row['candidates_kept']}/{row['candidates_total']} candidates, "
              f"{row['bytes'] / 1e6:.1f} MB {row['by_type']}", flush=True)

    todo = lambda c: want is None or c in want
    if todo("eagle_s_2024"):
        print("eagle_s_2024", flush=True)
        kw, flags = eagle_case()
        print(f"  Eagle S flagged, minutes after 10:13:04: {flags}")
        save(write_case("eagle_s_2024", CASES["eagle_s_2024"], kw["found"], kw["tracks"], kw["extra"], kw["notes"]))
    if todo("terry_2012"):
        print("terry_2012", flush=True)
        kw = terry_case()
        save(write_case("terry_2012", CASES["terry_2012"], kw["found"], kw["tracks"], kw["extra"], kw["notes"]))
    for cid, spec in CASES.items():
        if cid.startswith(("fi_replay_", "eagle", "terry")) or not todo(cid):
            continue
        print(cid, flush=True)
        tracks, found, outages = run_window(spec)
        save(write_case(cid, spec, found, tracks))
        del tracks, found
    # replay days and the all-days counts: day by day, memory is the limit
    rows = []
    days = COUNT_DAYS if (not a.no_counts and want is None) else []
    days = sorted(set(days) | {d for d in REPLAY_DAYS if todo(f"fi_replay_{d}")})
    for day in days:
        print("day", day, flush=True)
        row, (spec, found, tracks) = counts_for_day(day)
        rows.append(row)
        if day in REPLAY_DAYS and todo(f"fi_replay_{day}"):
            save(write_case(f"fi_replay_{day}", CASES[f"fi_replay_{day}"], found, tracks))
        print("  ", row, flush=True)
        del found, tracks
    if rows and not a.no_counts and want is None:
        pd.DataFrame(rows).to_csv(CASES_DIR / "detector_counts.csv", index=False)
        print("wrote detector_counts.csv")


if __name__ == "__main__":
    main()
