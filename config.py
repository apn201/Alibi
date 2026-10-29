"""Paths, data coverage and the source catalogue. Every path can be overridden by environment.

Coverage matters because "no data" must never read as "nothing happened": a query outside
the area and period our profile data covers is reported as unavailable.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("ALIBI_DATA", ROOT / "data"))
PROFILE_DB = Path(os.environ.get("ALIBI_PROFILE_DB", DATA / "derived" / "profile_db"))
CACHE = Path(os.environ.get("ALIBI_CACHE", DATA / "derived" / "alibi_cache"))
LEDGER = Path(os.environ.get("ALIBI_LEDGER", DATA / "alibi-ledger.sqlite"))
CONTEXT = Path(os.environ.get("ALIBI_CONTEXT", DATA / "context"))
SANCTIONS = Path(os.environ.get("ALIBI_SANCTIONS", DATA / "external" / "sanctions"))
ENVCACHE = Path(os.environ.get("ALIBI_ENVCACHE", DATA / "envcache"))
OPENAPI_YAML = ROOT / "alibi-openapi.yaml"

PROFILE_VERSION = os.environ.get("ALIBI_PROFILE_VERSION", "pdb-2026-10-28")
MAX_BODY_BYTES = 5 * 1024 * 1024
MAX_BATCH_BYTES = 25 * 1024 * 1024
MIN_TRACK_POINTS = 10
DEFAULT_SENSITIVITY = 0.5

# Where and when the segment data behind own_habit, place and fleet exists.
# (name, lon_min, lon_max, lat_min, lat_max, t_start, t_end) with t as ISO dates, end exclusive.
COVERAGE = [
    ("dk", 3.0, 18.5, 53.5, 59.0, "2024-10-01", "2026-10-18"),
    ("fi", 19.5, 30.5, 58.8, 61.0, "2026-10-05", "2026-10-29"),
]
# Finnish waters for the Traficom context layers (restriction areas, navigational warnings).
FINNISH_WATERS = (19.0, 31.0, 58.8, 66.0)
NOTICES_FROM = "2026-10-19"  # first snapshot of the navigational warnings we recorded

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
