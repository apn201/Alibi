"""Read single members of a large remote ZIP via HTTP range requests.

The Danish AIS archive stores older years as monthly ZIPs of 10-35 GB. A ZIP keeps its
table of contents at the end, so one range request finds the members and another fetches
just the day we want - no need to download the whole month.
"""

from __future__ import annotations

import io
import urllib.request
import zipfile

USER_AGENT = "apn201/alibi-lab 0.1"


class RangeFile(io.RawIOBase):
    """A read-only, seekable file over HTTP Range requests (with a small read-ahead buffer)."""

    def __init__(self, url: str, block: int = 1 << 20):
        self.url, self.block, self.pos = url, block, 0
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as r:
            self.size = int(r.headers["Content-Length"])
        self._buf_start, self._buf = -1, b""

    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.pos

    def seek(self, offset, whence=io.SEEK_SET):
        self.pos = offset if whence == io.SEEK_SET else self.pos + offset if whence == io.SEEK_CUR else self.size + offset
        return self.pos

    def _fetch(self, start: int, end: int) -> bytes:
        req = urllib.request.Request(self.url, headers={"User-Agent": USER_AGENT, "Range": f"bytes={start}-{end - 1}"})
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.read()

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        n = min(n, self.size - self.pos)
        if n <= 0:
            return b""
        if not (self._buf_start <= self.pos and self.pos + n <= self._buf_start + len(self._buf)):
            start = self.pos
            self._buf = self._fetch(start, min(self.size, start + max(n, self.block)))
            self._buf_start = start
        off = self.pos - self._buf_start
        out = self._buf[off:off + n]
        self.pos += len(out)
        return out

    def readinto(self, b):
        data = self.read(len(b))
        b[:len(data)] = data
        return len(data)


def members(url: str) -> list[zipfile.ZipInfo]:
    return zipfile.ZipFile(RangeFile(url)).infolist()


def extract(url: str, member: str, dest) -> int:
    """Copy one member's compressed bytes into a new local single-member ZIP (keeps it small on disk)."""
    zf = zipfile.ZipFile(RangeFile(url, block=16 << 20))
    info = zf.getinfo(member)
    with zf.open(info) as src, zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as out:
        with out.open(info.filename, "w", force_zip64=True) as dst:
            while chunk := src.read(16 << 20):
                dst.write(chunk)
    return info.file_size
