"""CLI: fill the environmental cache for the demo cases or a custom region and span.

  python tools/fetch_copernicus.py --all-cases
  python tools/fetch_copernicus.py --case eagle_s
  python tools/fetch_copernicus.py --region dk --start 2026-02-01 --end 2026-02-07
Needs `copernicusmarine login` once. Set PYTHONUTF8=1 on Windows.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from alibi.env import fetch as F  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case", choices=sorted(F.CASES))
    ap.add_argument("--all-cases", action="store_true")
    ap.add_argument("--region", choices=sorted(F.REGIONS))
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--pad-days", type=int, default=1, help="extra UTC days either side (default 1)")
    ap.add_argument("--root", help="cache root (default data/envcache or $ALIBI_ENVCACHE)")
    a = ap.parse_args(argv)
    if not F.credentials_present():
        print("No Copernicus Marine credentials found. Run: copernicusmarine login", file=sys.stderr)
        return 2
    if a.all_cases:
        jobs = [(n, *v) for n, v in F.CASES.items()]
    elif a.case:
        jobs = [(a.case, *F.CASES[a.case])]
    elif a.region and a.start and a.end:
        jobs = [("custom", a.region, a.start, a.end)]
    else:
        ap.error("give --case, --all-cases, or --region with --start and --end")
    total, bad = 0, 0
    for name, region, s, e in jobs:
        for st in F.fetch_span(region, s, e, a.root, a.pad_days):
            total += st["bytes"]
            bad += len(st["errors"])
            print(f"{name:11s} {st['region']:3s} {st['dataset']:48s} fetched={st['fetched']:3d} skipped={st['skipped']:3d} "
                  f"n/a={st['out_of_range']:3d} {st['bytes']/1e6:7.1f} MB {'ERR ' + st['errors'][0] if st['errors'] else ''}")
    print(f"downloaded {total/1e6:.1f} MB, {bad} failed runs")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
