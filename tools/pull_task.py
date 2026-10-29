"""Hourly scheduled task: pull closed hours from Umbrel into data/ais, log to data/pull.log.

Run by Windows Task Scheduler as `pythonw tools/pull_task.py` (no console window).
The share credentials live in Windows Credential Manager (cmdkey), never here.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from alibi_recorder.pull import pull, pull_context  # noqa: E402
from alibi_recorder.verify import verify  # noqa: E402

SOURCE = r"\\umbrel.local\alibi-data (Umbrel)"
DEST = ROOT / "data" / "ais"
LOG = ROOT / "data" / "pull.log"


def main() -> int:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        def log(msg: str) -> None:
            fh.write(f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} {msg}\n")
            fh.flush()

        try:
            res = pull(SOURCE, DEST, log=log)
            ctx = Path(SOURCE) / "context"
            if (ctx / "index.jsonl").exists():  # context recorder output, once deployed on Umbrel
                cres = pull_context(ctx, DEST.parent / "context", log=log)
                res.errors += cres.errors
                res.conflicts += cres.conflicts
            lines: list[str] = []
            verify(DEST, out=lines.append, deep=False)
            for line in lines:
                if line.startswith(("hour coverage", "BAD", "ledger")):
                    log(f"VERIFY   {line}")
            return 1 if res.errors or res.conflicts else 0
        except Exception as exc:  # share offline, PC away from home, ...: try again next hour
            log(f"FAILED   {exc!r}")
            return 2


if __name__ == "__main__":
    raise SystemExit(main())
