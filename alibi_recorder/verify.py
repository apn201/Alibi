"""alibi-recorder verify <dir>: is every closed hour intact, and how much of time is covered?"""

from __future__ import annotations

import gzip
import json
import time
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .store import hour_key, sha256_file


def _hours(first: datetime, last: datetime):
    t = first.replace(minute=0, second=0, microsecond=0)
    while t <= last:
        yield t.strftime("%Y%m%d-%H")
        t += timedelta(hours=1)


def _ranges(keys: list[str]) -> list[str]:
    """Collapse consecutive hour keys into 'a .. b (n h)' strings."""
    out, run = [], []
    for k in keys:
        if run and datetime.strptime(k, "%Y%m%d-%H") - datetime.strptime(run[-1], "%Y%m%d-%H") == timedelta(hours=1):
            run.append(k)
            continue
        if run:
            out.append(run)
        run = [k]
    if run:
        out.append(run)
    return [f"{r[0]}" if len(r) == 1 else f"{r[0]} .. {r[-1]} ({len(r)} h)" for r in out]


def verify(root: Path, now: float | None = None, out=print, deep: bool = True) -> int:
    """deep=False: coverage only, no re-hash or re-read (files pulled by `pull` were checked on arrival)."""
    root = Path(root)
    now = time.time() if now is None else now
    bad = 0
    present: set[str] = set()
    lines_total = 0

    closed = sorted(root.glob("*/*/*/ais-*.jsonl.gz"))
    for gz in closed:
        key = gz.name[4:15]  # YYYYMMDD-HH; also matches imported siblings like ais-...-HH-pc.jsonl.gz
        present.add(key)
        if not deep:
            continue
        sha = gz.with_name(gz.name + ".sha256")
        problems = []
        if not sha.is_file():
            problems.append("no .sha256")
        else:
            want = sha.read_text(encoding="ascii").split()[0]
            if sha256_file(gz) != want:
                problems.append("sha256 MISMATCH")
        try:
            n = bad_lines = 0
            with gzip.open(gz, "rb") as fh:
                for raw in fh:
                    n += 1
                    try:
                        json.loads(raw)
                    except ValueError:
                        bad_lines += 1
            lines_total += n
            if bad_lines:
                # expected after a kill -9: the half-written last line is kept, not repaired
                out(f"note     {gz.name}: {bad_lines} unparseable line(s) of {n}")
        except (OSError, EOFError, zlib.error) as exc:
            problems.append(f"gzip broken: {exc}")
        if problems:
            bad += 1
            out(f"BAD      {gz.relative_to(root)}: {', '.join(problems)}")

    for plain in sorted(root.glob("*/*/*/ais-*.jsonl")):
        key = plain.name[4:15]
        present.add(key)
        if key != hour_key(now):
            out(f"open     {plain.relative_to(root)} is a past hour still uncompressed (recorder down?)")

    # gaps.jsonl is the live ledger; gaps-<source>.jsonl are ledgers imported with sibling files.
    ledgers = sorted(root.glob("gaps*.jsonl"))
    per_ledger: list[list[dict]] = []
    for ledger in ledgers:
        evs = []
        for raw in ledger.read_bytes().splitlines():
            try:
                evs.append(json.loads(raw))
            except ValueError:
                continue
        per_ledger.append(evs)
    events = [e for evs in per_ledger for e in evs]
    starts = [e["ts"] for e in events if e.get("event") == "start"]

    first_ts = min(starts) if starts else None
    if first_ts is None and present:
        first_ts = datetime.strptime(min(present), "%Y%m%d-%H").replace(tzinfo=timezone.utc).timestamp()
    if first_ts is None:
        out("nothing recorded yet")
        return 1

    first = datetime.fromtimestamp(first_ts, timezone.utc)
    last = datetime.fromtimestamp(now, timezone.utc)
    hours = list(_hours(first, last))
    missing = [h for h in hours if h not in present]
    covered = len(hours) - len(missing)

    up = _union_seconds([iv for evs in per_ledger for iv in _connected_intervals(evs, now)]) if events else None
    span = now - first_ts
    out(f"closed files   {len(closed)} ({lines_total:,} lines), {bad} bad" if deep else
        f"closed files   {len(closed)} (quick: not re-read)")
    out(f"since          {first:%Y-%m-%d %H:%M} UTC ({span / 3600:.1f} h)")
    out(f"hour coverage  {covered}/{len(hours)} hours have a file = {100 * covered / len(hours):.1f} %")
    if up is not None:
        out(f"mqtt coverage  connected {up / 3600:.1f} h of {span / 3600:.1f} h = {100 * up / span:.1f} % (gap ledger)")
    if missing:
        out("hours with no file:")
        for r in _ranges(missing):
            out(f"  {r}")
    gaps = [e for e in events if e.get("event") in ("disconnect", "stale", "crash", "disk_pause", "fallback_on")]
    if gaps:
        out(f"ledger         {len(gaps)} gap events (disconnect/stale/crash/disk_pause/fallback_on)")
    return 1 if bad else 0


def _union_seconds(intervals: list[tuple[float, float]]) -> float:
    """Total length covered by any interval (two recorders running at once count once)."""
    total, end = 0.0, float("-inf")
    for a, b in sorted(intervals):
        if b <= end:
            continue
        total += b - max(a, end)
        end = b
    return total


def _connected_intervals(events: list[dict], now: float) -> list[tuple[float, float]]:
    """connect -> (disconnect|stale|stop|crash|start) intervals in one ledger."""
    out, since = [], None
    for e in events:
        ev = e.get("event")
        if ev == "connect":
            if since is None:
                since = e["ts"]
        elif ev in ("disconnect", "stale", "stop", "start"):
            if since is not None:
                out.append((since, e["ts"]))
                since = None
        elif ev == "crash":
            if since is not None:
                out.append((since, max(since, e.get("last_rx") or e["ts"])))
                since = None
    if since is not None:
        out.append((since, now))
    return out
