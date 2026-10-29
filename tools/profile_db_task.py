"""Scheduled task: bring the profile DB up to date, log to data/derived/profile_db/build.log.

Run by Windows Task Scheduler as `pythonw tools/profile_db_task.py`. Incremental: only days
without segments are processed, so it can be re-run any time (e.g. once more after the cut-off).
"""

import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from alibi_lab import profile_db  # noqa: E402

LOG = profile_db.DB / "build.log"


def main() -> int:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        def log(msg: str) -> None:
            fh.write(f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} {msg}\n")
            fh.flush()

        log("START")
        try:
            profile_db.build(log=log)
        except Exception:
            log("FAILED " + traceback.format_exc())
            return 1
        log("END")
    return 0


if __name__ == "__main__":
    sys.exit(main())
