"""The capture loop. One process: MQTT thread writes, main thread keeps watch.

Main thread, once a second: flush/rotate files, detect stale feed, reconnect with
jittered backoff, switch the REST fallback on and off, check disk, print stats.
"""

from __future__ import annotations

import random
import shutil
import signal
import ssl
import threading
import time
import uuid
from collections import Counter, deque
from datetime import datetime, timezone

from . import rest
from .config import Config
from .store import GapLedger, HourlyWriter, last_data_rx

GB = 1e9


def parse_topic(topic: str) -> tuple[str | None, str]:
    """'vessels-v2/230123456/location' -> ('230123456', 'location'). Either spelling, any kind."""
    parts = topic.split("/")
    if len(parts) >= 3 and parts[1].isdigit():
        return parts[1], parts[-1]
    return None, parts[-1] if len(parts) > 1 else topic


def kind_label(kind: str) -> str:
    return "location" if kind in ("location", "locations") else kind


def make_paho_client(cfg: Config, on_connect, on_disconnect, on_message):
    import paho.mqtt.client as mqtt

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"{cfg.app_name}; {uuid.uuid4()}",
        transport="websockets",
        protocol=mqtt.MQTTv311,
    )
    client.ws_set_options(path=cfg.mqtt_path)
    client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
    client.on_connect = lambda c, u, flags, rc, props=None: on_connect(not rc.is_failure, str(rc))
    client.on_disconnect = lambda c, u, flags, rc, props=None: on_disconnect(str(rc))
    client.on_message = lambda c, u, msg: on_message(msg.topic, msg.payload)
    client.reconnect_delay_set(3600, 3600)  # reconnects are ours, not paho's

    class Handle:
        def start(self):
            client.connect_async(cfg.mqtt_host, cfg.mqtt_port, keepalive=60)
            client.loop_start()

        def subscribe(self):
            client.subscribe(cfg.mqtt_topic, qos=0)

        def stop(self):
            try:
                client.disconnect()
            except Exception:
                pass
            client.loop_stop()

    return Handle()


class Recorder:
    def __init__(self, cfg: Config, *, client_factory=None, clock=time.time, log=print, rest_enabled=True):
        self.cfg = cfg
        self.clock = clock
        self.log = log
        self.rest_enabled = rest_enabled
        self.client_factory = client_factory or make_paho_client
        self.root = cfg.root
        self.writer = HourlyWriter(self.root, flush_s=cfg.flush_s, fsync_s=cfg.fsync_s, log=log)
        self.ledger = GapLedger(self.root / "gaps.jsonl")
        self.stop_event = threading.Event()
        self._lock = threading.Lock()

        # connection state (guarded by _lock where touched from the MQTT thread)
        self._gen = 0
        self._client = None
        self._connected = False
        self._attempt_at = 0.0
        self._needs_reset = False
        self._reset_reason = ""
        self._failures = 0
        self._next_attempt = 0.0
        self._connect_times: deque[float] = deque()
        self._last_msg = 0.0
        self._awaiting_first_msg = False
        self._down_since = clock()
        self._last_msg_at_connect = 0.0
        self._snapshot_retry = 0.0
        self.fallback = False

        # stats
        self._kinds: Counter[str] = Counter()
        self._mmsi_seen: dict[str, float] = {}
        self._bytes_window: deque[tuple[float, int]] = deque([(clock(), 0)])
        self._day = self._utc_day(clock())
        self._bytes_base = 0
        self._disk_paused = False
        self._last_disk_warn = 0.0

    @staticmethod
    def _utc_day(ts: float) -> str:
        return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")

    # -- MQTT callbacks (MQTT thread) ------------------------------------------------
    def _on_message(self, gen: int, topic: str, payload: bytes) -> None:
        rx = self.clock()  # first thing: the receive time is the point of the exercise
        self.writer.write(rx, topic, payload)
        mmsi, kind = parse_topic(topic)
        with self._lock:
            if gen == self._gen and self._awaiting_first_msg:
                self._awaiting_first_msg = False
                gap = rx - self._last_msg if self._last_msg else None
                self.ledger.log("resume", f"first message after connect; silence {gap:.1f} s" if gap else
                                "first message after connect", ts=rx)
            self._last_msg = rx
            self._kinds[kind_label(kind)] += 1
            if mmsi:
                self._mmsi_seen[mmsi] = rx

    def _on_connect(self, gen: int, ok: bool, reason: str) -> None:
        with self._lock:
            if gen != self._gen:
                return
            if not ok:
                self._needs_reset, self._reset_reason = True, f"connect refused: {reason}"
                return
            self._connected = True
            self._awaiting_first_msg = True
            self._failures = 0
            self._last_msg_at_connect = self.clock()
            client = self._client
        client.subscribe()
        self.ledger.log("connect", f"{self.cfg.mqtt_host}:{self.cfg.mqtt_port}{self.cfg.mqtt_path} sub {self.cfg.mqtt_topic}")
        self.log(f"CONNECT  {self.cfg.mqtt_host} subscribed {self.cfg.mqtt_topic}")

    def _on_disconnect(self, gen: int, reason: str) -> None:
        with self._lock:
            if gen != self._gen:
                return
            self._needs_reset, self._reset_reason = True, f"disconnected: {reason}"

    # -- connection management (main thread) -----------------------------------------
    def _connect(self, now: float) -> None:
        while self._connect_times and now - self._connect_times[0] > 60:
            self._connect_times.popleft()
        if len(self._connect_times) >= self.cfg.max_connects_per_min:
            self._next_attempt = self._connect_times[0] + 60.5
            return
        self._connect_times.append(now)
        with self._lock:
            self._gen += 1
            gen = self._gen
            self._connected = False
            self._needs_reset = False
            self._attempt_at = now
        client = self.client_factory(
            self.cfg,
            lambda ok, reason: self._on_connect(gen, ok, reason),
            lambda reason: self._on_disconnect(gen, reason),
            lambda topic, payload: self._on_message(gen, topic, payload),
        )
        with self._lock:
            self._client = client
        try:
            client.start()
        except Exception as exc:
            with self._lock:
                self._needs_reset, self._reset_reason = True, f"connect error: {exc!r}"

    def _teardown(self, now: float, event: str, detail: str) -> None:
        with self._lock:
            client, self._client = self._client, None
            was_connected = self._connected
            self._connected = False
            self._gen += 1  # late callbacks from the old client are ignored
            if was_connected:
                self._down_since = now
        if client is not None:
            threading.Thread(target=client.stop, daemon=True).start()
        if was_connected or event == "stale":
            self.ledger.log(event, detail, ts=now)
            self.log(f"{event.upper():8} {detail}")
        else:
            self.log(f"RETRY    {detail}")
        self._failures += 1
        base = min(self.cfg.backoff_max_s, self.cfg.backoff_min_s * 2 ** (self._failures - 1))
        delay = max(self.cfg.backoff_min_s, random.uniform(base / 2, base))
        self._next_attempt = now + delay

    def _watch_connection(self, now: float) -> None:
        with self._lock:
            client, connected = self._client, self._connected
            needs_reset, reason = self._needs_reset, self._reset_reason
            last = max(self._last_msg, self._last_msg_at_connect)
        if client is None:
            if now >= self._next_attempt:
                self._connect(now)
            return
        if needs_reset:
            self._teardown(now, "disconnect", reason)
        elif connected and now - last > self.cfg.stale_s:
            self._teardown(now, "stale", f"no message for {now - last:.0f} s while connected; reconnecting")
        elif not connected and now - self._attempt_at > self.cfg.connect_timeout_s:
            self._teardown(now, "disconnect", f"connect timed out after {self.cfg.connect_timeout_s:.0f} s")

    # -- REST thread --------------------------------------------------------------
    def _rest_loop(self) -> None:
        last_poll = 0.0
        while not self.stop_event.wait(5):
            now = self.clock()
            with self._lock:
                down_for = 0.0 if self._connected else now - self._down_since
            if down_for > self.cfg.fallback_after_s and not self._disk_paused:
                if not self.fallback:
                    self.fallback = True
                    self.ledger.log("fallback_on", f"MQTT down {down_for:.0f} s; polling /locations every "
                                    f"{self.cfg.fallback_poll_s:.0f} s", ts=now)
                if now - last_poll >= self.cfg.fallback_poll_s:
                    last_poll = now
                    dest = self.root / "rest" / f"locations-{rest.utc_stamp(now)}.json.gz"
                    try:
                        n = rest.fetch_to_gz(self.cfg.rest_base + "/locations", dest, self.cfg.app_name)
                        self.log(f"FALLBACK {dest.name} {n / 1e3:.0f} kB")
                    except Exception as exc:
                        self.log(f"FALLBACK failed: {exc!r}")
            elif self.fallback and down_for == 0.0:
                self.fallback = False
                self.ledger.log("fallback_off", "MQTT back", ts=now)
            self._daily_snapshot(now)

    def _daily_snapshot(self, now: float) -> None:
        if self._disk_paused:
            return
        dest = self.root / "rest" / f"vessels-{self._utc_day(now)}.json.gz"
        if dest.exists() or now < self._snapshot_retry:
            return
        try:
            n = rest.fetch_to_gz(self.cfg.rest_base + "/vessels", dest, self.cfg.app_name)
            self.log(f"SNAPSHOT {dest.name} {n / 1e3:.0f} kB")
        except Exception as exc:
            self._snapshot_retry = now + 600
            self.log(f"SNAPSHOT failed, retry in 10 min: {exc!r}")

    # -- disk and stats -------------------------------------------------------------
    def free_bytes(self) -> int:
        return shutil.disk_usage(self.root).free

    def _check_disk(self, now: float) -> None:
        free = self.free_bytes()
        if free < self.cfg.disk_stop_gb * GB:
            if not self._disk_paused:
                self._disk_paused = True
                self.writer.paused = True
                self.ledger.log("disk_pause", f"free {free / GB:.2f} GB < {self.cfg.disk_stop_gb} GB; "
                                "not writing messages", ts=now)
        elif self._disk_paused and free > (self.cfg.disk_stop_gb + 0.5) * GB:
            self._disk_paused = False
            self.writer.paused = False
            self.ledger.log("disk_resume", f"free {free / GB:.2f} GB; writing again "
                            f"({self.writer.dropped_paused} messages not stored while paused)", ts=now)
        if free < self.cfg.disk_warn_gb * GB and now - self._last_disk_warn >= 60:
            self._last_disk_warn = now
            self.log(f"!!!!!!!! DISK LOW: {free / GB:.2f} GB free in {self.root.resolve()} "
                     f"{'- WRITING STOPPED' if self._disk_paused else ''} !!!!!!!!")

    def stats_line(self, now: float) -> str:
        with self._lock:
            kinds, self._kinds = self._kinds, Counter()
            cutoff = now - 3600
            for mmsi in [m for m, t in self._mmsi_seen.items() if t < cutoff]:
                del self._mmsi_seen[mmsi]
            unique = len(self._mmsi_seen)
        written = self.writer.bytes
        day = self._utc_day(now)
        if day != self._day:
            self._day, self._bytes_base = day, written
        today = written - self._bytes_base
        self._bytes_window.append((now, written))
        while self._bytes_window and now - self._bytes_window[0][0] > 3600:
            self._bytes_window.popleft()
        t0, b0 = self._bytes_window[0]
        span = now - t0
        per_day = (written - b0) / span * 86400 / GB if span >= 60 else float("nan")
        mins = self.cfg.stats_s / 60
        rates = " ".join(f"{k}={v / mins:.0f}" for k, v in sorted(kinds.items())) or "none"
        state = "up" if self._connected else ("FALLBACK" if self.fallback else "DOWN")
        return (f"STATS    mqtt={state} msg/min: {rates} | mmsi 1h={unique} | today {today / 1e6:.1f} MB raw (this run) | "
                f"projected {per_day:.2f} GB/day raw | free {self.free_bytes() / GB:.1f} GB")

    # -- lifecycle ------------------------------------------------------------------
    def startup(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        now = self.clock()
        last = self.ledger.last_event()
        if last is not None and last.get("event") not in ("stop", "crash"):
            last_rx = last_data_rx(self.root)
            self.ledger.log("crash", "previous run ended without a clean stop", ts=now,
                            last_event=last, last_rx=last_rx)
            self.log(f"CRASH    previous run had no clean stop; last data line rx={last_rx}")
        for path in self.writer.recover(now):
            self.log(f"RECOVER  compressing leftover {path.name}")
        self.ledger.log("start", f"{self.cfg.app_name}; data {self.root.resolve()}", ts=now)
        self.log(f"START    {self.cfg.app_name} -> {self.root.resolve()}")

    def shutdown(self, reason: str) -> None:
        with self._lock:
            client, self._client = self._client, None
            self._gen += 1
        if client is not None:
            client.stop()
        self.writer.close()
        self.ledger.log("stop", reason)
        self.log(f"STOP     {reason}")

    def run(self, install_signals: bool = True) -> None:
        if install_signals:
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, lambda s, f: self.stop_event.set())
        self.startup()
        if self.rest_enabled:
            ok, msg = rest.clock_check(self.cfg.rest_base, self.cfg.app_name)
            self.log(f"CLOCK    {msg}" if ok else f"WARNING  clock not confirmed in sync: {msg}")
            threading.Thread(target=self._rest_loop, name="rest", daemon=True).start()
        next_stats = self.clock() + self.cfg.stats_s
        while not self.stop_event.is_set():
            now = self.clock()
            self.writer.tick(now)
            self._watch_connection(now)
            self._check_disk(now)
            if now >= next_stats:
                next_stats = now + self.cfg.stats_s
                self.log(self.stats_line(now))
            self.stop_event.wait(1.0)
        self.shutdown("signal" if install_signals else "stopped")
