"""alibi-recorder pull SRC [DEST]: copy closed recordings from another recorder's data dir.

SRC is any folder holding a recorder's `ais/` tree: a network share of the Umbrel
data folder, a mounted drive, or a local folder. DEST defaults to the configured data
dir. Run it as often as you like; it only ever adds files.

- Closed hours (`.jsonl.gz` with a `.sha256` beside it) are copied and checked
  against that checksum before they appear under their final name.
- The open hour (plain `.jsonl`) is skipped: it is still being written.
- A file already in DEST is never replaced. Same content -> skipped; different
  content -> reported as a conflict and left alone.
- `rest/*.json.gz` snapshots are copied when missing.
- The source's live ledger `gaps.jsonl` is mirrored as `gaps-<label>.jsonl`. It
  only ever grows; a shorter source copy is refused.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .store import sha256_file


@dataclass
class PullResult:
    copied: list[str] = field(default_factory=list)
    skipped: int = 0
    open_hours: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    bytes: int = 0


def _copy_atomic(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    with open(src, "rb") as fi, open(tmp, "wb") as fo:
        shutil.copyfileobj(fi, fo, 1 << 20)
        fo.flush()
        os.fsync(fo.fileno())
    os.replace(tmp, dest)


def _want_sha(sha_file: Path) -> str:
    return sha_file.read_text(encoding="ascii").split()[0]


def copy_closed_hour(src_gz: Path, dest_gz: Path, res: PullResult, *, recheck: bool = False) -> None:
    """Copy one closed hour + .sha256, verified. dest_gz may have a different name (siblings)."""
    src_sha = src_gz.with_name(src_gz.name + ".sha256")
    dest_sha = dest_gz.with_name(dest_gz.name + ".sha256")
    want = _want_sha(src_sha)
    if dest_gz.exists():
        have = _want_sha(dest_sha) if dest_sha.exists() and not recheck else sha256_file(dest_gz)
        if have == want:
            res.skipped += 1
        else:
            res.conflicts.append(f"{dest_gz.name}: DEST differs from source, left untouched")
        return
    tmp = dest_gz.with_name(dest_gz.name + ".part")
    dest_gz.parent.mkdir(parents=True, exist_ok=True)
    for attempt in (1, 2):
        shutil.copyfile(src_gz, tmp)
        if sha256_file(tmp) == want:
            break
        if attempt == 2:
            tmp.unlink()
            res.errors.append(f"{src_gz.name}: checksum mismatch after copy (twice), not stored")
            return
    with open(tmp, "rb+") as fh:
        os.fsync(fh.fileno())
    os.replace(tmp, dest_gz)
    with open(dest_sha.with_name(dest_sha.name + ".part"), "w", encoding="ascii", newline="\n") as fh:
        fh.write(f"{want}  {dest_gz.name}\n")
    os.replace(dest_sha.with_name(dest_sha.name + ".part"), dest_sha)
    res.copied.append(dest_gz.name)
    res.bytes += dest_gz.stat().st_size


def pull(src: Path, dest: Path, *, label: str = "umbrel", recheck: bool = False, log=print) -> PullResult:
    src, dest = Path(src), Path(dest)
    if (src / "ais").is_dir() and not (src / "gaps.jsonl").exists():
        src = src / "ais"  # accept the data folder or its ais/ subfolder
    if not src.is_dir():
        raise FileNotFoundError(f"source not found: {src}")
    res = PullResult()

    for gz in sorted(src.glob("*/*/*/ais-*.jsonl.gz")):
        rel = gz.relative_to(src)
        if not gz.with_name(gz.name + ".sha256").exists():
            res.errors.append(f"{rel}: no .sha256 at source (compression still running?), skipped this time")
            continue
        try:
            copy_closed_hour(gz, dest / rel, res, recheck=recheck)
        except OSError as exc:
            res.errors.append(f"{rel}: {exc!r}")
    res.open_hours = [p.name for p in src.glob("*/*/*/ais-*.jsonl")]

    for snap in sorted((src / "rest").glob("*.json.gz")):
        target = dest / "rest" / snap.name
        if target.exists():
            if target.stat().st_size != snap.stat().st_size:
                res.conflicts.append(f"rest/{snap.name}: DEST differs in size, left untouched")
            else:
                res.skipped += 1
            continue
        _copy_atomic(snap, target)
        res.copied.append(f"rest/{snap.name}")
        res.bytes += snap.stat().st_size

    ledger = src / "gaps.jsonl"
    if ledger.is_file():
        mirror = dest / f"gaps-{label}.jsonl"
        if mirror.exists() and mirror.stat().st_size > ledger.stat().st_size:
            res.conflicts.append(f"{mirror.name}: source ledger is shorter than the mirror, not replaced")
        else:
            _copy_atomic(ledger, mirror)

    log(f"PULL     {src} -> {dest}")
    log(f"         copied {len(res.copied)} files ({res.bytes / 1e6:.1f} MB), {res.skipped} already present, "
        f"open hour skipped: {', '.join(res.open_hours) or '-'}")
    for c in res.conflicts:
        log(f"CONFLICT {c}")
    for e in res.errors:
        log(f"ERROR    {e}")
    return res


def pull_context(src: Path, dest: Path, *, label: str = "umbrel", log=print) -> PullResult:
    """Copy context snapshots (alibi_recorder/context.py) that are not yet in dest.

    src/dest: the context folders (holding index.jsonl). Each stored file is checked against
    the sha256 the index recorded for it; the index itself is mirrored as index-<label>.jsonl."""
    src, dest = Path(src), Path(dest)
    res = PullResult()
    index = src / "index.jsonl"
    if not index.is_file():
        raise FileNotFoundError(f"no context index at {index}")
    want: dict[str, str] = {}
    for raw in index.read_bytes().splitlines():
        try:
            e = json.loads(raw)
        except ValueError:
            continue
        if e.get("status") == "stored":
            want[e["file"]] = e["sha256"]
    for rel, sha in want.items():
        target = dest / rel
        if target.exists():
            res.skipped += 1
            continue
        tmp = target.with_name(target.name + ".part")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(src / rel, tmp)
        except OSError as exc:
            res.errors.append(f"{rel}: {exc!r}")
            continue
        if sha256_file(tmp) != sha:
            tmp.unlink()
            res.errors.append(f"{rel}: checksum mismatch after copy, not stored")
            continue
        os.replace(tmp, target)
        res.copied.append(rel)
        res.bytes += target.stat().st_size
    mirror = dest / f"index-{label}.jsonl"
    if mirror.exists() and mirror.stat().st_size > index.stat().st_size:
        res.conflicts.append(f"{mirror.name}: source index is shorter than the mirror, not replaced")
    else:
        _copy_atomic(index, mirror)
    log(f"CONTEXT  {src} -> {dest}: copied {len(res.copied)} files ({res.bytes / 1e3:.0f} kB), "
        f"{res.skipped} already present, {len(res.errors)} errors")
    for e in res.errors:
        log(f"ERROR    {e}")
    return res
