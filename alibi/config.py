"""Paths, data coverage and the source catalogue. Every path can be overridden by environment.

Coverage matters because "no data" must never read as "nothing happened": a query outside
the area and period our profile data covers is reported as unavailable.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Development reads the live data/ tree; a deployment by git clone reads the committed snapshot/.
_LIVE = ROOT / "data"
DATA = Path(os.environ.get("ALIBI_DATA") or (_LIVE if (_LIVE / "derived" / "profile_db" / "vessel_profiles.parquet").exists()
                                             else ROOT / "snapshot"))
PROFILE_DB = Path(os.environ.get("ALIBI_PROFILE_DB", DATA / "derived" / "profile_db"))
# Writable state stays outside snapshot/ (git-ignored data/), whichever tree is read.
CACHE = Path(os.environ.get("ALIBI_CACHE", _LIVE / "derived" / "alibi_cache"))
LEDGER = Path(os.environ.get("ALIBI_LEDGER", _LIVE / "alibi-ledger.sqlite"))
CONTEXT = Path(os.environ.get("ALIBI_CONTEXT", DATA / "context"))
SANCTIONS = Path(os.environ.get("ALIBI_SANCTIONS", DATA / "external" / "sanctions"))
ENVCACHE = Path(os.environ.get("ALIBI_ENVCACHE", DATA / "envcache"))
OPENAPI_YAML = ROOT / "alibi-openapi.yaml"

MAX_BODY_BYTES = 5 * 1024 * 1024
MAX_BATCH_BYTES = 25 * 1024 * 1024
MIN_TRACK_POINTS = 10
DEFAULT_SENSITIVITY = 0.5


def _spans() -> dict[str, tuple[str, str]]:
    """First and last segment day per source, from the files actually present (days are added nightly)."""
    out = {}
    for src in ("dk", "fi"):
        days = sorted(f.stem for f in (PROFILE_DB / "segments" / src).glob("????-??-??.parquet"))
        if days:
            out[src] = (days[0], days[-1])
    return out


def _version() -> dict:
    try:
        return json.loads((DATA / "VERSION.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


SPANS = _spans()
_V = _version()
PROFILE_VERSION = os.environ.get("ALIBI_PROFILE_VERSION") or _V.get("profile_version") or     ("pdb-" + max(d[1] for d in SPANS.values()) if SPANS else "pdb-unknown")

# Where and when the segment data behind own_habit, place and fleet exists:
# (name, lon_min, lon_max, lat_min, lat_max, first day, day after the last), dates from the segment files.
_BOXES = {"dk": (3.0, 18.5, 53.5, 59.0), "fi": (19.5, 30.5, 58.8, 61.0)}
COVERAGE = [(src, *_BOXES[src], first, (date.fromisoformat(last) + timedelta(days=1)).isoformat())
            for src, (first, last) in SPANS.items() if src in _BOXES]
# Finnish waters for the Traficom context layers (restriction areas, navigational warnings).
FINNISH_WATERS = (19.0, 31.0, 58.8, 66.0)


def coverage_sentence() -> str:
    names = {"dk": "Danish waters", "fi": "the Gulf of Finland"}
    parts = [f"{names[s]} from {a} to {b}" for s, (a, b) in SPANS.items() if s in names]
    return ("Coverage: ALIBI's AIS history covers " + " and ".join(parts) if parts else
            "Coverage: no AIS history is loaded") + "; elsewhere, habit, place and fleet evidence is unavailable."


# Source catalogue (GET /sources). `profile` is the baseline and always on.
SOURCES = [
    {"id": "profile", "title": "Expected behaviour (own profile, class prototype, this journey)", "kind": "behaviour",
     "lamp": None, "attribution": "ALIBI profile DB from Danish Maritime Authority AIS and Fintraffic Digitraffic AIS"},
    {"id": "sea_state", "title": "Sea state: wind, waves, currents", "kind": "behaviour", "lamp": "WX",
     "attribution": "E.U. Copernicus Marine Service Information"},
    {"id": "ice", "title": "Sea ice", "kind": "behaviour", "lamp": "ICE",
     "attribution": "E.U. Copernicus Marine Service Information; Fintraffic winter navigation"},
    {"id": "own_habit", "title": "Own habit: this ship at this place before", "kind": "behaviour", "lamp": "PLC",
     "attribution": "ALIBI profile DB (Danish Maritime Authority AIS, Fintraffic Digitraffic AIS)"},
    {"id": "place", "title": "Place: local normal speed, restriction areas, port approach", "kind": "behaviour",
     "lamp": "PLC", "attribution": "ALIBI profile DB; Traficom restriction areas (CC BY 4.0)"},
    {"id": "fleet", "title": "Fleet: other ships nearby at the same time", "kind": "behaviour", "lamp": "TRF",
     "attribution": "ALIBI profile DB (Danish Maritime Authority AIS, Fintraffic Digitraffic AIS)"},
    {"id": "notices", "title": "Navigational warnings in force", "kind": "behaviour", "lamp": "PLC",
     "attribution": "Traficom navigational warnings (CC BY 4.0)"},
    {"id": "position_quality", "title": "Position quality (accuracy flags, jumps, reporting gaps)", "kind": "quality",
     "lamp": "GNSS", "attribution": "The submitted track"},
    {"id": "identity", "title": "Identity context: EU designation, GUR listing", "kind": "identity", "lamp": None,
     "attribution": "EU designations via Danish Maritime Authority list (2026-07-24); GUR listing via OpenSanctions (CC BY-NC 4.0)"},
]
SOURCE_IDS = [s["id"] for s in SOURCES]
