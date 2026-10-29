"""REST side: fallback polling of /locations, the daily /vessels snapshot, a clock check.

Responses are stored whole. Digitraffic requires gzip, so the body normally arrives
gzipped and is written to disk byte for byte as received.
"""

from __future__ import annotations

import gzip
import os
import platform
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path


def _request(url: str, app_name: str, method: str = "GET", timeout: float = 60.0):
    req = urllib.request.Request(
        url, method=method, headers={"Digitraffic-User": app_name, "Accept-Encoding": "gzip"}
    )
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_to_gz(url: str, dest: Path, app_name: str) -> int:
    """GET url, store the body as dest (.json.gz), atomically. Returns bytes stored."""
    with _request(url, app_name) as resp:
        body = resp.read()
        encoding = resp.headers.get("Content-Encoding", "")
    if encoding != "gzip":
        body = gzip.compress(body)
    gzip.decompress(body)  # refuse to store a truncated download
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    with open(tmp, "wb") as fh:
        fh.write(body)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, dest)
    return len(body)


def utc_stamp(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def clock_check(base_url: str, app_name: str) -> tuple[bool, str]:
    """Is the host clock trustworthy? (ok, message). Never raises."""
    notes = []
    synced = _os_ntp_status()
    if synced is not None:
        notes.append(f"OS NTP sync: {'yes' if synced else 'NO'}")
    try:
        t0 = time.time()
        with _request(base_url + "/locations?mmsi=1", app_name, timeout=15) as resp:
            # CloudFront caches ~60 s: a cache hit carries the original Date plus Age.
            server = parsedate_to_datetime(resp.headers["Date"]).timestamp() + float(resp.headers.get("Age", 0))
        t1 = time.time()
        offset = (t0 + t1) / 2 - server
        notes.append(f"offset vs digitraffic Date header {offset:+.1f} s (1 s resolution)")
        http_ok = abs(offset) <= 2.0
    except Exception as exc:
        notes.append(f"could not compare with server time: {exc!r}")
        http_ok = None
    ok = synced is not False and http_ok is True
    return ok, "; ".join(notes)


def _os_ntp_status() -> bool | None:
    try:
        if platform.system() == "Linux":
            out = subprocess.run(
                ["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            return {"yes": True, "no": False}.get(out)
        if platform.system() == "Windows":
            out = subprocess.run(["w32tm", "/query", "/status"], capture_output=True, text=True, timeout=5)
            if out.returncode != 0:
                return None
            text = out.stdout.lower()
            if "local cmos clock" in text or "free-running" in text:
                return False
            return "last successful sync time" in text or None
    except (OSError, subprocess.SubprocessError):
        return None
    return None
