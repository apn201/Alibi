"""Fetch the AIS around the listed incidents (alibi_lab/incidents.py), one case at a time.

    python tools/fetch_incidents.py              # all cases
    python tools/fetch_incidents.py terry_2012   # one case

Streams only the needed days out of the Danish archive. Log: data/external/dma_incidents/fetch.log
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alibi_lab import incidents as I  # noqa: E402

LOG = I.OUT / "fetch.log"


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


if __name__ == "__main__":
    wanted = set(sys.argv[1:])
    for case in I.CASES:
        if wanted and case.key not in wanted:
            continue
        if not wanted and case.key == "simon_b_2014":
            continue  # "July 2014" has no day: would need the whole month; fetch on request only
        try:
            I.fetch(case, days_before=1, days_after=0, log=log)
        except Exception as exc:
            log(f"{case.key} FAILED {exc!r}")
    log("done")
