"""Pack a deployable ALIBI: the committed code plus the data the service reads, in one tar.gz.

    python tools/make_bundle.py            -> dist/alibi-deploy-<UTC date>.tar.gz

The repo holds code only (data/ is git-ignored, see PRIOR_WORK.md). A server needs the profile
snapshot, the Copernicus cache, the replay cases and the identity lists too. Third-party case
data (Eagle S, `"third_party": true` in the case file) is left out: we show results, not data.
"""

from __future__ import annotations

import io
import re
import json
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

INCLUDE = [
    "derived/profile_db/vessel_profiles.parquet",
    "derived/profile_db/class_profiles.parquet",
    "derived/profile_db/vessel_keys.parquet",
    "derived/profile_db/segments",
    "derived/alibi_cache",
    "envcache",
    "external/sanctions",
    "context/restriction_areas",
    "context/nav_warnings_a",
    "context/nav_warnings_l",
    "context/nav_warnings_p",
    "context/index-umbrel.jsonl",
]


def third_party_cases() -> set[str]:
    out = set()
    for f in (DATA / "cases").glob("*.json"):
        if f.name == "index.json":
            continue
        with open(f, encoding="utf-8") as fh:
            head = fh.read(4096)
        if re.search(r'"third_party":\s*true', head):
            out.add(f.name)
    return out


def main() -> int:
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    out = dist / f"alibi-deploy-{datetime.now(timezone.utc):%Y%m%d-%H%M}.tar.gz"
    code = subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=ROOT, check=True, capture_output=True).stdout
    skip = third_party_cases()
    with tarfile.open(out, "w:gz") as tar:
        with tarfile.open(fileobj=io.BytesIO(code)) as src:
            for m in src.getmembers():
                tar.addfile(m, src.extractfile(m) if m.isfile() else None)
        for rel in INCLUDE:
            p = DATA / rel
            if p.exists():
                tar.add(p, arcname=f"data/{rel}")
        for f in sorted((DATA / "cases").glob("*")):
            if f.name in skip:
                print(f"left out (third party): {f.name}")
                continue
            if f.name == "index.json":
                idx = json.loads(f.read_text(encoding="utf-8"))
                cases = idx.get("cases", idx) if isinstance(idx, dict) else idx
                kept = [c for c in cases if f"{c.get('case_id')}.json" not in skip]
                body = json.dumps({"cases": kept} if isinstance(idx, dict) else kept, indent=1).encode()
                info = tarfile.TarInfo("data/cases/index.json")
                info.size = len(body)
                tar.addfile(info, io.BytesIO(body))
                continue
            tar.add(f, arcname=f"data/cases/{f.name}")
    print(f"{out} {out.stat().st_size / 1e6:.0f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
