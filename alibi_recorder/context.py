"""Context recorder: snapshots of live-only context that explains ship behaviour.

Like AIS, these sources only show the present, so their history must be recorded:
    nav_warnings_{p,l,a}  Traficom navigational warnings in force (points, lines, areas)
    winter_locations      Digitraffic winter navigation: ports/locations, restrictions
    winter_vessels        icebreakers and their assistance activity
    winter_dirways        dirways (icebreaker-defined routes in ice)
    port_visits           Digitraffic port visits (expected, arrived, departed)
    port_calls            full port-call list of the previous UTC day (queryable by date, so daily)
    aton_faults_*         Vaylavirasto: current faults in aids to navigation (hourly)
    restriction_areas     Vaylavirasto restriction areas incl. anchoring bans (daily, stored on change)
    waterway_signs        Vaylavirasto waterway signs incl. cable signs (daily, stored on change)
    fairways_vl1/_vl2     commercial fairways with their depths (daily, stored on change)

Layout:
    data/context/{source}/YYYY/MM/DD/{source}-YYYYMMDDTHHMMSSZ.json.gz   response as received, gzip
    data/context/index.jsonl     one line per check: stored | unchanged | error, sha256 of the stored file

A response whose content (ignoring top-level update timestamps) equals the previous stored
one is not stored again; the index records that it was checked and unchanged. Files are
written once, atomically, and never changed. Licences: Traficom, Fintraffic and Vaylavirasto
data CC BY 4.0. No secrets.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import signal
import threading
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import APP_NAME

TRAFICOM_WFS = ("https://julkinen.traficom.fi/inspirepalvelu/avoin/wfs?service=WFS&version=2.0.0&request=GetFeature"
                "&outputFormat=application/json&srsName=EPSG:4326&typeNames=avoin:")
DIGITRAFFIC = "https://meri.digitraffic.fi/api"
VAYLA_WFS = ("https://avoinapi.vaylapilvi.fi/vaylatiedot/ows?service=WFS&version=2.0.0&request=GetFeature"
             "&outputFormat=application/json&srsName=EPSG:4326&typeNames=vesivaylatiedot:")
RETRY_S = 600


@dataclass(frozen=True)
class Source:
    name: str
    url: str  # may contain {yesterday}
    every: str  # "hour" | "day"


SOURCES = [
    Source("nav_warnings_p", TRAFICOM_WFS + "navigational_warnings_p", "hour"),
    Source("nav_warnings_l", TRAFICOM_WFS + "navigational_warnings_l", "hour"),
    Source("nav_warnings_a", TRAFICOM_WFS + "navigational_warnings_a", "hour"),
    Source("winter_locations", DIGITRAFFIC + "/winter-navigation/v2/locations", "hour"),
    Source("winter_vessels", DIGITRAFFIC + "/winter-navigation/v2/vessels", "hour"),
    Source("winter_dirways", DIGITRAFFIC + "/winter-navigation/v2/dirways", "hour"),
    Source("port_visits", DIGITRAFFIC + "/port-call/v2/visits", "hour"),
    Source("port_calls", DIGITRAFFIC + "/port-call/v1/port-calls?date={yesterday}", "day"),
    Source("aton_faults_merchant", VAYLA_WFS + "vesivaylien_turvalaiteviat_kauppamerenkulku", "hour"),
    Source("aton_faults_shallow", VAYLA_WFS + "vesivaylien_turvalaiteviat_matalavaylat", "hour"),
    Source("restriction_areas", VAYLA_WFS + "rajoitusalue_a_uusi", "day"),  # incl. anchoring bans
    Source("waterway_signs", VAYLA_WFS + "vesiliikennemerkit_uusi", "day"),  # incl. cable signs
    Source("fairways_vl1", VAYLA_WFS + "vesivaylat_vl1", "day"),
    Source("fairways_vl2", VAYLA_WFS + "vesivaylat_vl2", "day"),
]


def _utc(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, timezone.utc)


# Keys that only say when a response was produced, at any depth (Vayla stamps every feature
# with its extraction date "irrotus_pvm"). Ignored when deciding whether content changed.
VOLATILE = ("updated", "timestamp", "numberreturned", "irrotus")


def _strip(doc):
    if isinstance(doc, dict):
        return {k: _strip(v) for k, v in doc.items() if not any(w in k.lower() for w in VOLATILE)}
    if isinstance(doc, list):
        return [_strip(v) for v in doc]
    return doc


def content_hash(body: bytes) -> str:
    """sha256 of the content, ignoring keys that only say when it was produced."""
    try:
        doc = json.loads(body)
    except ValueError:
        return hashlib.sha256(body).hexdigest()
    return hashlib.sha256(json.dumps(_strip(doc), sort_keys=True).encode()).hexdigest()


def fetch(url: str, app_name: str = APP_NAME, timeout: float = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": app_name, "Digitraffic-User": app_name,
                                               "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
    json.loads(body)  # refuse truncated or non-JSON answers
    return body


class ContextRecorder:
    def __init__(self, root: Path, sources: list[Source] = SOURCES, fetcher=fetch, clock=time.time, log=print):
        self.root, self.sources, self.fetcher, self.clock, self.log = Path(root), sources, fetcher, clock, log
        self.root.mkdir(parents=True, exist_ok=True)
        self.index = self.root / "index.jsonl"
        self.stop_event = threading.Event()
        self.last_hash: dict[str, str] = {}
        self.last_done: dict[str, str] = {}  # source -> period key last checked ("YYYYMMDDHH" or "YYYYMMDD")
        self.retry_at: dict[str, float] = {}  # after an error, wait before asking that source again
        self._load_state()

    def _load_state(self) -> None:
        if not self.index.is_file():
            return
        for raw in self.index.read_bytes().splitlines():
            try:
                e = json.loads(raw)
            except ValueError:
                continue
            if e.get("status") in ("stored", "unchanged"):
                self.last_hash[e["source"]] = e["content_sha256"]
                self.last_done[e["source"]] = e["period"]

    def _log(self, entry: dict) -> None:
        with open(self.index, "ab") as fh:
            fh.write((json.dumps(entry) + "\n").encode())
            fh.flush()
            os.fsync(fh.fileno())

    @staticmethod
    def period(source: Source, now: float) -> str:
        return _utc(now).strftime("%Y%m%d%H" if source.every == "hour" else "%Y%m%d")

    def due(self, now: float) -> list[Source]:
        return [s for s in self.sources
                if self.last_done.get(s.name) != self.period(s, now) and now >= self.retry_at.get(s.name, 0)]

    def check(self, source: Source, now: float) -> dict:
        url = source.url.format(yesterday=(_utc(now) - timedelta(days=1)).strftime("%Y-%m-%d"))
        entry = {"ts": round(now, 3), "source": source.name, "period": self.period(source, now), "url": url}
        try:
            body = self.fetcher(url)
        except Exception as exc:  # retried next minute; the index keeps the failure
            entry.update(status="error", detail=repr(exc)[:300])
            self.retry_at[source.name] = now + RETRY_S
            self._log(entry)
            return entry
        h = content_hash(body)
        if h == self.last_hash.get(source.name):
            entry.update(status="unchanged", content_sha256=h)
        else:
            stamp = _utc(now).strftime("%Y%m%dT%H%M%SZ")
            path = self.root / source.name / stamp[:4] / stamp[4:6] / stamp[6:8] / f"{source.name}-{stamp}.json.gz"
            path.parent.mkdir(parents=True, exist_ok=True)
            data = gzip.compress(body)
            tmp = path.with_name(path.name + ".tmp")
            with open(tmp, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
            entry.update(status="stored", content_sha256=h, file=str(path.relative_to(self.root)).replace("\\", "/"),
                         sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
        self.last_hash[source.name] = h
        self.last_done[source.name] = entry["period"]
        self._log(entry)
        return entry

    def tick(self) -> list[dict]:
        now = self.clock()
        return [self.check(s, now) for s in self.due(now)]

    def run(self, install_signals: bool = True, every_s: float = 60) -> None:
        if install_signals:
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, lambda s, f: self.stop_event.set())
        self._log({"ts": round(self.clock(), 3), "source": "*", "status": "start", "detail": APP_NAME})
        self.log(f"CONTEXT  start -> {self.root.resolve()} ({len(self.sources)} sources)")
        while not self.stop_event.is_set():
            for e in self.tick():
                if e["status"] != "unchanged":
                    self.log(f"CONTEXT  {e['source']:16} {e['status']} {e.get('bytes', '')} {e.get('detail', '')}")
            self.stop_event.wait(every_s)
        self._log({"ts": round(self.clock(), 3), "source": "*", "status": "stop", "detail": "signal"})
        self.log("CONTEXT  stop")
