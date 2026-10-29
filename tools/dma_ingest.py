"""Download and compact the Danish AIS archive for a date range, in parallel.

    python tools/dma_ingest.py 2025-10-01 2026-10-18 --workers 3
    python tools/dma_ingest.py 2024-11-17 2024-11-19 --keep-raw     # incident days: keep the zip

Days already ingested are skipped, so the command can be re-run after an interruption.
Output and log: F:/alibi-data/dma/ (outside Dropbox). See alibi_lab/dma.py.
"""

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alibi_lab import dma  # noqa: E402

LOG = dma.ROOT / "ingest.log"


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def one(day: date, keep_raw: bool) -> str:
    out = []
    dma.run([day], keep_raw={day} if keep_raw else set(), log=out.append)
    return out[0] if out else f"{day}  already done"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("start", type=date.fromisoformat)
    ap.add_argument("end", type=date.fromisoformat)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--keep-raw", action="store_true")
    a = ap.parse_args()
    days = [a.start + timedelta(d) for d in range((a.end - a.start).days + 1)]
    todo = [d for d in days if d.isoformat() not in dma.done_days()]
    log(f"START  {a.start}..{a.end}: {len(days)} days, {len(todo)} to do, {a.workers} workers")
    with ProcessPoolExecutor(a.workers) as pool:
        for f in as_completed([pool.submit(one, d, a.keep_raw) for d in todo]):
            log(f.result())
    log(f"END    {len(dma.done_days())} days ingested in total")


if __name__ == "__main__":
    main()
