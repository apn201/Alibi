"""Append-only storage: hourly JSONL files and the gap ledger.

Layout (UTC hours, by receive time):
    data/ais/YYYY/MM/DD/ais-YYYYMMDD-HH.jsonl          the open hour
    data/ais/YYYY/MM/DD/ais-YYYYMMDD-HH.jsonl.gz       a closed hour, never touched again
    data/ais/YYYY/MM/DD/ais-YYYYMMDD-HH.jsonl.gz.sha256  sha256sum format, of the .gz
    data/ais/gaps.jsonl                                start/stop/connect/... events

One line per message: {"rx": <epoch s>, "topic": "...", "payload": <as received>}.
A valid JSON payload is embedded with only the whitespace between tokens removed
(the feed pretty-prints); keys, order and number literals stay exactly as sent.
Anything that is not valid JSON is stored as a string under "raw".
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path


def _reject_constant(name: str):
    raise ValueError(f"non-standard JSON constant {name}")


def format_line(rx: float, topic: str, payload: bytes) -> str:
    """Wrap one message. Never raises, never drops."""
    head = f'{{"rx": {rx:.3f}, "topic": {json.dumps(topic)}, '
    try:
        text = payload.decode("utf-8")
        json.loads(text, parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError):
        return head + f'"raw": {json.dumps(payload.decode("utf-8", errors="backslashreplace"))}}}\n'
    return head + f'"payload": {minify(text)}}}\n'


_WS = frozenset(" \t\r\n")


def minify(text: str) -> str:
    """Drop whitespace outside strings. Digitraffic pretty-prints its payloads; this puts
    them on one line while every token (numbers included) stays byte-identical."""
    out, in_str, esc = [], False, False
    for ch in text:
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
            out.append(ch)
        elif ch not in _WS:
            out.append(ch)
    return "".join(out)


def hour_key(rx: float) -> str:
    return datetime.fromtimestamp(rx, timezone.utc).strftime("%Y%m%d-%H")


def hour_path(root: Path, key: str) -> Path:
    return root / key[0:4] / key[4:6] / key[6:8] / f"ais-{key}.jsonl"


def _fsync_dir(path: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def compress_closed(raw: Path) -> Path:
    """gzip a closed hour beside itself, write .sha256, then drop the plain file.

    Crash-safe at every step: the .gz appears only by atomic rename, and the plain
    file is removed only after the .gz and its checksum are on disk.
    """
    gz = raw.with_name(raw.name + ".gz")
    sha = gz.with_name(gz.name + ".sha256")
    if not gz.exists():
        tmp = gz.with_name(gz.name + ".tmp")
        with open(raw, "rb") as src, open(tmp, "wb") as dst:
            with gzip.GzipFile(filename=raw.name, mode="wb", fileobj=dst, compresslevel=6) as zf:
                shutil.copyfileobj(src, zf, 1 << 20)
            dst.flush()
            os.fsync(dst.fileno())
        os.replace(tmp, gz)
        _fsync_dir(gz.parent)
    if not sha.exists():
        tmp = sha.with_name(sha.name + ".tmp")
        with open(tmp, "w", encoding="ascii", newline="\n") as fh:
            fh.write(f"{sha256_file(gz)}  {gz.name}\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, sha)
    raw.unlink()
    return gz


class HourlyWriter:
    """Thread-safe. write() from the MQTT thread, tick() from the main loop."""

    def __init__(self, root: Path, *, flush_s: float = 1.0, fsync_s: float = 5.0, log=print):
        self.root = Path(root)
        self.flush_s, self.fsync_s = flush_s, fsync_s
        self.log = log
        self._lock = threading.Lock()
        self._fh = None
        self._key: str | None = None
        self._last_flush = self._last_fsync = time.monotonic()
        self._dirty = False
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gzip")
        self.paused = False
        self.lines = 0
        self.bytes = 0
        self.dropped_paused = 0
        self.last_rx: float | None = None

    # -- startup -----------------------------------------------------------------
    def recover(self, now: float) -> list[Path]:
        """Compress any plain hour file left behind by a crash (except the current hour)."""
        current = hour_key(now)
        leftovers = sorted(p for p in self.root.glob("*/*/*/ais-*.jsonl") if p.stem[4:] != current)
        for path in leftovers:
            self._submit_compress(path)
        return leftovers

    # -- writing -----------------------------------------------------------------
    def write(self, rx: float, topic: str, payload: bytes) -> None:
        line = format_line(rx, topic, payload).encode("utf-8")
        with self._lock:
            if self.paused:
                self.dropped_paused += 1
                return
            key = hour_key(rx)
            if key != self._key:
                self._switch(key)
            self._fh.write(line)
            self._dirty = True
            self.lines += 1
            self.bytes += len(line)
            self.last_rx = rx
            if time.monotonic() - self._last_flush >= self.flush_s:
                self._flush(fsync=False)

    def _switch(self, key: str) -> None:
        path = hour_path(self.root, key)
        if path.with_name(path.name + ".gz").exists():
            # Clock stepped back into an hour that is already closed. Never reopen it:
            # keep writing to the current file (rx inside each line stays truthful).
            if self._fh is not None:
                return
            key = hour_key(time.time())
            path = hour_path(self.root, key)
        self._close_current()
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(path, "ab")
        if fh.tell() > 0:
            with open(path, "rb") as check:
                check.seek(-1, os.SEEK_END)
                if check.read(1) != b"\n":
                    fh.write(b"\n")  # a kill -9 left half a line: end it, keep it, start clean
        self._fh, self._key = fh, key

    def _close_current(self) -> None:
        if self._fh is None:
            return
        self._flush(fsync=True)
        path = Path(self._fh.name)
        self._fh.close()
        self._fh, self._key = None, None
        self._submit_compress(path)

    def _submit_compress(self, path: Path) -> None:
        def job():
            try:
                gz = compress_closed(path)
                self.log(f"CLOSED   {gz.name}  {gz.stat().st_size / 1e6:.1f} MB")
            except Exception as exc:  # leave the plain file in place; recover() retries on next start
                self.log(f"ERROR    compressing {path}: {exc!r}")
        self._pool.submit(job)

    def _flush(self, *, fsync: bool) -> None:
        if self._fh is None:
            return
        now = time.monotonic()
        if self._dirty:
            self._fh.flush()
            self._dirty = False
            self._last_flush = now
        if fsync:
            os.fsync(self._fh.fileno())
            self._last_fsync = now

    def tick(self, now: float | None = None) -> None:
        """Flush, fsync, and close the hour once the clock has moved past it."""
        now = time.time() if now is None else now
        with self._lock:
            if self._key is not None and hour_key(now) > self._key:
                self._close_current()
                return
            mono = time.monotonic()
            if mono - self._last_flush >= self.flush_s:
                self._flush(fsync=False)
            if mono - self._last_fsync >= self.fsync_s:
                self._flush(fsync=True)

    def close(self, wait: bool = True) -> None:
        """Flush and close the open hour. It stays plain until its hour has passed."""
        with self._lock:
            if self._fh is not None:
                self._flush(fsync=True)
                self._fh.close()
                self._fh, self._key = None, None
        self._pool.shutdown(wait=wait)

    def drain(self) -> None:
        """Wait for queued compressions (tests)."""
        self._pool.submit(lambda: None).result()


class GapLedger:
    """data/ais/gaps.jsonl. Every event is fsynced: this file is the recorder's alibi."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def last_event(self) -> dict | None:
        if not self.path.is_file():
            return None
        with open(self.path, "rb") as fh:
            lines = fh.read().splitlines()
        for raw in reversed(lines):
            try:
                return json.loads(raw)
            except ValueError:
                continue
        return None

    def log(self, event: str, detail: str = "", ts: float | None = None, **extra) -> dict:
        rec = {"ts": round(time.time() if ts is None else ts, 3), "event": event, "detail": detail, **extra}
        line = (json.dumps(rec) + "\n").encode("utf-8")
        with self._lock, open(self.path, "ab") as fh:
            if fh.tell() > 0:
                with open(self.path, "rb") as check:
                    check.seek(-1, os.SEEK_END)
                    if check.read(1) != b"\n":
                        fh.write(b"\n")
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
        return rec


def last_data_rx(root: Path) -> float | None:
    """rx of the last complete line on disk, for crash reports. Looks at the newest plain file."""
    plain = sorted(Path(root).glob("*/*/*/ais-*.jsonl"))
    if not plain:
        return None
    with open(plain[-1], "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - 65536))
        tail = fh.read().splitlines()
    for raw in reversed(tail):
        try:
            return float(json.loads(raw)["rx"])
        except (ValueError, KeyError, TypeError):
            continue
    return None
