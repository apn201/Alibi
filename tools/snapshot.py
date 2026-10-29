"""Copy what the ALIBI service needs from data/ into snapshot/, which is committed to the repo.

    python tools/snapshot.py          -> snapshot/ (same layout as data/), snapshot/VERSION.json

The raw AIS (our recording, the Danish archive) stays out of the repo: once processed, the
history lives in the profile DB, and new days arrive through the nightly job (tools/nightly.py).
A server can then run from a plain `git clone`. Only the latest snapshot of each slow-changing
context layer is kept; the GUR list is cut down to its vessel entries.
"""

from __future__ import annotations

import glob
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SNAP = ROOT / "snapshot"
PDB = "derived/profile_db"
LATEST_ONLY = ["restriction_areas", "waterway_signs", "fairways_vl1", "fairways_vl2"]
ALL_OF = ["nav_warnings_a", "nav_warnings_l", "nav_warnings_p"]


def sync_tree(src: Path, dst: Path) -> int:
    """Copy new or changed files, remove files that are gone from src. Returns files copied."""
    n = 0
    dst.mkdir(parents=True, exist_ok=True)
    keep = set()
    for f in src.rglob("*"):
        if f.is_dir():
            continue
        rel = f.relative_to(src)
        keep.add(rel)
        out = dst / rel
        if out.exists() and out.stat().st_size == f.stat().st_size and out.stat().st_mtime >= f.stat().st_mtime:
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, out)
        n += 1
    for f in list(dst.rglob("*")):
        if f.is_file() and f.relative_to(dst) not in keep:
            f.unlink()
    return n


def main() -> int:
    pdb = DATA / PDB
    (SNAP / PDB).mkdir(parents=True, exist_ok=True)
    for name in ("vessel_profiles", "class_profiles", "vessel_keys", "identities", "stop_areas", "own_stops"):
        shutil.copy2(pdb / f"{name}.parquet", SNAP / PDB / f"{name}.parquet")
    copied = sync_tree(pdb / "segments", SNAP / PDB / "segments")

    sanc = SNAP / "external" / "sanctions"
    sanc.mkdir(parents=True, exist_ok=True)
    for f in (DATA / "external" / "sanctions").glob("dma_eu_designated_vessels_*.csv"):
        shutil.copy2(f, sanc / f.name)
    gur = DATA / "external" / "sanctions" / "opensanctions_ua_war_sanctions_entities.ftm.json"
    if gur.exists():
        with open(gur, encoding="utf-8") as src, open(sanc / gur.name, "w", encoding="utf-8", newline="\n") as dst:
            dst.writelines(line for line in src if '"schema":"Vessel"' in line)

    # Files are replaced and removed one by one, never the folder: Dropbox briefly locks folders it syncs.
    ctx = SNAP / "context"
    wanted = set()
    for layer in LATEST_ONLY + ALL_OF:
        files = sorted(glob.glob(str(DATA / "context" / layer / "*" / "*" / "*" / "*.json.gz")))
        for f in files[-1:] if layer in LATEST_ONLY else files:
            out = ctx / Path(f).relative_to(DATA / "context")
            wanted.add(out)
            if not out.exists() or out.stat().st_size != Path(f).stat().st_size:
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, out)
    for f in [p for p in ctx.rglob("*") if p.is_file() and p not in wanted]:
        f.unlink()

    # Replay cases from open data only (Eagle S is third-party: results, not data). The live case is made on the server.
    cases = SNAP / "cases"
    cases.mkdir(parents=True, exist_ok=True)
    kept = []
    for f in sorted((DATA / "cases").glob("*.json")):
        with open(f, encoding="utf-8") as fh:
            head = fh.read(4096)
        if f.name == "index.json" or f.stem.startswith("live_") or re.search(r'"third_party":\s*true', head):
            continue
        shutil.copy2(f, cases / f.name)
        kept.append(f.stem)
    for f in cases.glob("*.json"):
        if f.stem not in kept and f.name != "index.json":
            f.unlink()
    idx = json.loads((DATA / "cases" / "index.json").read_text(encoding="utf-8"))
    rows = idx["cases"] if isinstance(idx, dict) else idx
    rows = [c for c in rows if c.get("case_id") in kept]
    (cases / "index.json").write_text(json.dumps({"cases": rows} if isinstance(idx, dict) else rows, indent=1),
                                      encoding="utf-8")

    spans = {}
    for src in ("dk", "fi"):
        days = sorted(p.stem for p in (SNAP / PDB / "segments" / src).glob("*.parquet"))
        if days:
            spans[src] = [days[0], days[-1]]
    last = max(s[1] for s in spans.values())
    version = {"profile_version": f"pdb-{last}", "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "spans": spans,
               "sources": {"dk": "Danish Maritime Authority AIS archive (aisdata.ais.dk)",
                           "fi": "Fintraffic Digitraffic marine AIS, recorded by ALIBI (CC BY 4.0)"}}
    (SNAP / "VERSION.json").write_text(json.dumps(version, indent=1) + "\n", encoding="utf-8")
    size = sum(f.stat().st_size for f in SNAP.rglob("*") if f.is_file())
    print(f"snapshot {version['profile_version']}: {copied} segment files copied, {size / 1e6:.0f} MB in snapshot/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
