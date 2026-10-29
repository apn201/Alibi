"""The evidence ledger: every assessment with its input, configuration and findings, in SQLite.

A re-run with the same request, configuration and profile version must give the same
answer; the ledger is what lets an analyst check that later. One row per assessment (request
and result as JSON) and one row per finding, so evidence can be queried by source.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from . import config

SCHEMA = """
create table if not exists assessments (
    id text primary key, created text not null, profile_version text, model_version text,
    request text not null, result text not null, configuration text not null);
create table if not exists evidence (
    assessment_id text not null references assessments(id), source_id text not null, status text not null,
    explains real, summary text, source_reference text, details text);
create index if not exists evidence_by_assessment on evidence(assessment_id);
"""

_lock = threading.Lock()
_ready: set = set()


def path() -> Path:
    return config.LEDGER


@contextmanager
def _connect():
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p, timeout=10)
    try:
        if p not in _ready:  # once per file: schema, and a journal mode that does not fsync every insert
            con.executescript(SCHEMA)
            con.execute("pragma journal_mode=wal")
            _ready.add(p)
        con.execute("pragma synchronous=normal")
        yield con
        con.commit()
    finally:
        con.close()


def init() -> bool:
    try:
        with _lock, _connect() as con:
            con.execute("select count(*) from assessments").fetchone()
        return True
    except Exception:  # noqa: BLE001
        return False


def reference(assessment_id: str) -> str:
    return f"ledger:{path().name}#{assessment_id}"


def record(request: dict, result: dict) -> None:
    cfg = result["configuration"]
    with _lock, _connect() as con:
        con.execute("insert into assessments values (?,?,?,?,?,?,?)",
                    (result["assessment_id"], result["assessed_at"], cfg["profile_version"], cfg["model_version"],
                     json.dumps(request, separators=(",", ":")), json.dumps(result, separators=(",", ":")),
                     json.dumps(cfg, separators=(",", ":"))))
        con.executemany("insert into evidence values (?,?,?,?,?,?,?)",
                        [(result["assessment_id"], f["source_id"], f["status"], f.get("explains"), f["summary"],
                          f.get("source_reference"), json.dumps(f.get("details"), separators=(",", ":")))
                         for f in result["findings"]])


def get(assessment_id: str) -> dict | None:
    with _lock, _connect() as con:
        row = con.execute("select result from assessments where id = ?", (assessment_id,)).fetchone()
    return json.loads(row[0]) if row else None
