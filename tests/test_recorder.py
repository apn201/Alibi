import gzip
import hashlib
import json
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from alibi_recorder.config import Config
from alibi_recorder.recorder import Recorder, kind_label, parse_topic
from alibi_recorder.store import GapLedger, HourlyWriter, format_line, hour_path
from alibi_recorder.verify import verify

LOCATION = b'{"time":1668075025,"sog":10.7,"cog":326.6,"navStat":0,"rot":0,"posAcc":true,"raim":false,"heading":325,"lon":20.345818,"lat":60.03802}'
METADATA = (b'{"timestamp":1668075026035,"destination":"UST LUGA","name":"ARUNA CIHAN","draught":68,"eta":733376,'
            b'"posType":15,"refA":160,"refB":33,"refC":20,"refD":12,"callSign":"V7WW7","imo":9543756,"type":70}')
PRETTY = b'{\n  "cog" : 353.60,\n  "name" : "A  B\\" C",\n  "time" : 1791142966\n}'


def ts(y, mo, d, h, mi=0, s=0.0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp() + s


def read_hour(root: Path, key: str) -> list[dict]:
    path = hour_path(root, key)
    gz = path.with_name(path.name + ".gz")
    data = gzip.decompress(gz.read_bytes()) if gz.exists() else path.read_bytes()
    return [json.loads(line) for line in data.splitlines()]


# -- parsing ---------------------------------------------------------------------------

def test_samples_both_topic_spellings():
    for topic in ("vessels-v2/230123456/location", "vessels-v2/230123456/locations"):
        rec = json.loads(format_line(1791234567.123, topic, LOCATION))
        assert rec["topic"] == topic and rec["rx"] == 1791234567.123
        assert rec["payload"]["time"] == 1668075025  # epoch s, stored as is
        assert parse_topic(topic) == ("230123456", topic.rsplit("/", 1)[1])
        assert kind_label(parse_topic(topic)[1]) == "location"
    rec = json.loads(format_line(1.0, "vessels-v2/230123456/metadata", METADATA))
    assert rec["payload"]["timestamp"] == 1668075026035  # epoch ms, not converted
    assert rec["payload"]["name"] == "ARUNA CIHAN"
    assert parse_topic("vessels-v2/status") == (None, "status")


def test_payload_kept_exact_and_bad_payload_kept_raw():
    line = format_line(1.0, "t", PRETTY)
    assert '"cog":353.60' in line  # number literal untouched, only whitespace removed
    assert json.loads(line)["payload"]["name"] == 'A  B" C'  # whitespace inside strings kept
    assert line.count("\n") == 1
    bad = json.loads(format_line(1.0, "t", b'{"half": '))
    assert bad["raw"] == '{"half": ' and "payload" not in bad
    binary = json.loads(format_line(1.0, "t", b"\xff\x00"))
    assert "raw" in binary
    assert "raw" in json.loads(format_line(1.0, "t", b'{"x": NaN}'))


# -- rotation ----------------------------------------------------------------------------

def test_rotation_at_hour_boundary(tmp_path):
    w = HourlyWriter(tmp_path, log=lambda m: None)
    before = [ts(2026, 10, 4, 12, 59, s) for s in (58.0, 59.5, 59.999)]
    after = [ts(2026, 10, 4, 13, 0, s) for s in (0.0, 0.001, 1.0)]
    for i, rx in enumerate(before + after):
        w.write(rx, f"vessels-v2/{i}/location", LOCATION)
    w.tick(ts(2026, 10, 4, 14, 0, 1))  # clock passes 13:xx -> that hour closes too
    w.close()
    h12, h13 = read_hour(tmp_path, "20261004-12"), read_hour(tmp_path, "20261004-13")
    assert [r["topic"] for r in h12] == [f"vessels-v2/{i}/location" for i in range(3)]
    assert [r["topic"] for r in h13] == [f"vessels-v2/{i}/location" for i in range(3, 6)]
    for key in ("20261004-12", "20261004-13"):
        p = hour_path(tmp_path, key)
        gz, sha = p.with_name(p.name + ".gz"), p.with_name(p.name + ".gz.sha256")
        assert not p.exists() and gz.exists()
        assert sha.read_text().split()[0] == hashlib.sha256(gz.read_bytes()).hexdigest()


# -- kill -9 -------------------------------------------------------------------------------

WRITER_SCRIPT = r"""
import sys, time
from pathlib import Path
from alibi_recorder.store import HourlyWriter, GapLedger
root = Path(sys.argv[1])
GapLedger(root / "gaps.jsonl").log("start", "child")
w = HourlyWriter(root, flush_s=0.0)
payload = b'{"pad":"' + b"x" * 5000 + b'"}'
print("ready", flush=True)
while True:
    w.write(time.time(), "vessels-v2/230123456/location", payload)
"""


def test_kill9_mid_write_then_restart(tmp_path):
    child = subprocess.Popen([sys.executable, "-c", WRITER_SCRIPT, str(tmp_path)], stdout=subprocess.PIPE)
    assert child.stdout.readline().strip() == b"ready"
    time.sleep(1.0)
    child.kill()  # SIGKILL / TerminateProcess: no cleanup runs
    child.wait()

    files = list(tmp_path.glob("*/*/*/ais-*.jsonl"))
    assert files
    good = 0
    lines = files[0].read_bytes().split(b"\n")
    for i, raw in enumerate(lines):
        if not raw:
            continue
        try:
            json.loads(raw)
            good += 1
        except ValueError:
            assert i == len(lines) - 1, "only the very last line may be cut"
    assert good > 10

    cfg = Config(data_dir=str(tmp_path))
    rec = Recorder(cfg, client_factory=None, log=lambda m: None, rest_enabled=False)
    rec.startup()
    events = [json.loads(l) for l in (tmp_path / "gaps.jsonl").read_text().splitlines()]
    assert [e["event"] for e in events] == ["start", "crash", "start"]
    assert events[1]["last_rx"] is not None
    # writing again after the crash starts on a fresh line
    rec.writer.write(time.time(), "vessels-v2/1/location", LOCATION)
    rec.writer.close()
    for f in tmp_path.glob("*/*/*/ais-*.jsonl*"):
        if f.suffix == ".jsonl":
            last = f.read_bytes().splitlines()[-1]
            if b'"vessels-v2/1/location"' in last:
                assert json.loads(last)["payload"]["sog"] == 10.7


# -- stale feed --------------------------------------------------------------------------

class FakeClient:
    """Stands in for paho: connects, sends one message, then goes silent forever."""
    instances = []

    def __init__(self, cfg, on_connect, on_disconnect, on_message):
        self.on_connect, self.on_message = on_connect, on_message
        self.subscribed = self.stopped = False
        FakeClient.instances.append(self)

    def start(self):
        def go():
            self.on_connect(True, "Success")
            self.on_message("vessels-v2/230123456/location", LOCATION)
        threading.Thread(target=go, daemon=True).start()

    def subscribe(self):
        self.subscribed = True

    def stop(self):
        self.stopped = True


def test_silent_broker_fires_stale_and_reconnects(tmp_path):
    FakeClient.instances.clear()
    cfg = Config(data_dir=str(tmp_path), stale_s=1.5, backoff_min_s=0.2, backoff_max_s=0.5, stats_s=3600)
    rec = Recorder(cfg, client_factory=FakeClient, log=lambda m: None, rest_enabled=False)
    t = threading.Thread(target=rec.run, kwargs={"install_signals": False})
    t.start()
    deadline = time.time() + 15
    while time.time() < deadline and len(FakeClient.instances) < 2:
        time.sleep(0.1)
    time.sleep(0.5)
    rec.stop_event.set()
    t.join(10)
    events = [json.loads(l)["event"] for l in (tmp_path / "gaps.jsonl").read_text().splitlines()]
    assert len(FakeClient.instances) >= 2
    assert FakeClient.instances[0].stopped and FakeClient.instances[0].subscribed
    assert events[:5] == ["start", "connect", "resume", "stale", "connect"]
    assert events[-1] == "stop"


def test_connect_rate_stays_under_digitraffic_limit(tmp_path):
    attempts = []

    class Refuses(FakeClient):
        def start(self):
            attempts.append(time.time())
            self.on_connect(False, "Not authorized")

    cfg = Config(data_dir=str(tmp_path), backoff_min_s=0.0, backoff_max_s=0.0)
    rec = Recorder(cfg, client_factory=Refuses, log=lambda m: None, rest_enabled=False)
    now = 1000.0
    for _ in range(100):
        rec._watch_connection(now)
        now += 0.5
    assert len(attempts) <= cfg.max_connects_per_min


# -- disk full -----------------------------------------------------------------------------

def test_disk_full_pauses_writing_and_logs_gap(tmp_path):
    cfg = Config(data_dir=str(tmp_path))
    logs = []
    rec = Recorder(cfg, client_factory=FakeClient, log=logs.append, rest_enabled=False)
    rec.startup()
    free = {"b": 0.5e9}
    rec.free_bytes = lambda: free["b"]
    rec._check_disk(time.time())
    rec._on_message(rec._gen, "vessels-v2/1/location", LOCATION)  # process stays alive, message not written
    assert rec.writer.paused and rec.writer.lines == 0 and rec.writer.dropped_paused == 1
    assert any("DISK LOW" in m for m in logs)
    free["b"] = 50e9
    rec._check_disk(time.time())
    rec._on_message(rec._gen, "vessels-v2/1/location", LOCATION)
    assert not rec.writer.paused and rec.writer.lines == 1
    rec.shutdown("test")
    events = [json.loads(l) for l in (tmp_path / "gaps.jsonl").read_text().splitlines()]
    kinds = [e["event"] for e in events]
    assert "disk_pause" in kinds and "disk_resume" in kinds
    assert "1 messages not stored" in next(e for e in events if e["event"] == "disk_resume")["detail"]


def test_disk_warning_between_1_and_5_gb(tmp_path):
    logs = []
    rec = Recorder(Config(data_dir=str(tmp_path)), client_factory=FakeClient, log=logs.append, rest_enabled=False)
    rec.free_bytes = lambda: 3e9
    rec._check_disk(1000.0)
    rec._check_disk(1030.0)  # not again within the minute
    rec._check_disk(1061.0)
    assert sum("DISK LOW" in m for m in logs) == 2 and not rec.writer.paused


# -- verify ------------------------------------------------------------------------------

def test_verify_reports_coverage_and_corruption(tmp_path):
    w = HourlyWriter(tmp_path, log=lambda m: None)
    GapLedger(tmp_path / "gaps.jsonl").log("start", "", ts=ts(2026, 10, 4, 10, 30))
    for h in (10, 11, 13):
        w.write(ts(2026, 10, 4, h, 5), "vessels-v2/1/location", LOCATION)
    w.tick(ts(2026, 10, 4, 14, 1))
    w.close()
    out = []
    assert verify(tmp_path, now=ts(2026, 10, 4, 14, 2), out=out.append) == 0
    text = "\n".join(out)
    assert "3/5 hours" in text and "20261004-12" in text and "20261004-14" in text

    gz = next(tmp_path.glob("*/*/*/ais-20261004-11.jsonl.gz"))
    gz.write_bytes(gz.read_bytes()[:-5])
    out.clear()
    assert verify(tmp_path, now=ts(2026, 10, 4, 14, 2), out=out.append) == 1
    assert any("BAD" in m and "sha256 MISMATCH" in m for m in out)


def test_one_hour_reads_back_in_ten_lines(tmp_path):
    w = HourlyWriter(tmp_path, log=lambda m: None)
    for i in range(50):
        w.write(ts(2026, 10, 4, 9, 0, i), f"vessels-v2/{230000000 + i}/location", LOCATION)
    w.tick(ts(2026, 10, 4, 10, 0, 1))
    w.close()
    path = next(tmp_path.glob("*/*/*/ais-20261004-09.jsonl.gz"))
    # --- the "ten lines of Python" from the spec ---
    import gzip as gz_, json as json_
    rows = []
    with gz_.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            msg = json_.loads(line)
            if msg["topic"].endswith(("location", "locations")):
                p = msg["payload"]
                rows.append((msg["rx"], msg["topic"].split("/")[1], p["lat"], p["lon"], p["sog"]))
    # -----------------------------------------------
    assert len(rows) == 50 and rows[0][2] == 60.03802


def test_verify_counts_imported_sibling_files_and_ledgers(tmp_path):
    # PC recorded 10:30-11:41, Umbrel took over at 11:40: hour 11 has two files, two ledgers.
    pc, um = tmp_path / "pc", tmp_path / "um"
    for root, start, stop in ((pc, ts(2026, 10, 4, 10, 30), ts(2026, 10, 4, 11, 41)),
                              (um, ts(2026, 10, 4, 11, 40), None)):
        led = GapLedger(root / "gaps.jsonl")
        led.log("start", "", ts=start)
        led.log("connect", "", ts=start + 1)
        if stop:
            led.log("stop", "", ts=stop)
    w = HourlyWriter(pc, log=lambda m: None)
    for h in (10, 11):
        w.write(ts(2026, 10, 4, h, 35), "vessels-v2/1/location", LOCATION)
    w.tick(ts(2026, 10, 4, 12, 0, 1))
    w.close()
    w = HourlyWriter(um, log=lambda m: None)
    for h in (11, 12):
        w.write(ts(2026, 10, 4, h, 45), "vessels-v2/2/location", LOCATION)
    w.tick(ts(2026, 10, 4, 13, 0, 1))
    w.close()
    # import, the way it is done by hand: hour 10 as is, hour 11 as a -pc sibling, ledger as gaps-pc
    day = um / "2026" / "10" / "04"
    for name in ("ais-20261004-10.jsonl.gz", "ais-20261004-10.jsonl.gz.sha256"):
        (day / name).write_bytes((pc / "2026" / "10" / "04" / name).read_bytes())
    gz = (pc / "2026" / "10" / "04" / "ais-20261004-11.jsonl.gz").read_bytes()
    (day / "ais-20261004-11-pc.jsonl.gz").write_bytes(gz)
    (day / "ais-20261004-11-pc.jsonl.gz.sha256").write_text(
        f"{hashlib.sha256(gz).hexdigest()}  ais-20261004-11-pc.jsonl.gz\n")
    (um / "gaps-pc.jsonl").write_bytes((pc / "gaps.jsonl").read_bytes())

    out = []
    assert verify(um, now=ts(2026, 10, 4, 13, 30), out=out.append) == 0
    text = "\n".join(out)
    assert "4 (4 lines), 0 bad" in text
    assert "since          2026-10-04 10:30" in text
    assert "3/4 hours" in text and text.endswith("hours with no file:\n  20261004-13")  # 10, 11, 12 covered
    assert "connected 3.0 h of 3.0 h" in text  # 10:30:01 -> 13:30, overlap counted once


# -- pull ----------------------------------------------------------------------------------

def _recording(root: Path, hours, open_hour=None):
    led = GapLedger(root / "gaps.jsonl")
    led.log("start", "", ts=ts(2026, 10, 4, hours[0], 1))
    w = HourlyWriter(root, log=lambda m: None)
    for h in hours:
        w.write(ts(2026, 10, 4, h, 5), "vessels-v2/1/location", LOCATION)
    w.tick(ts(2026, 10, 4, hours[-1] + 1, 0, 1))
    if open_hour is not None:
        w.write(ts(2026, 10, 4, open_hour, 5), "vessels-v2/1/location", LOCATION)
    w.close()
    (root / "rest").mkdir(exist_ok=True)
    (root / "rest" / "vessels-2026-10-04.json.gz").write_bytes(gzip.compress(b"[]"))


def test_pull_copies_closed_hours_verified_and_is_idempotent(tmp_path):
    from alibi_recorder.pull import pull

    src, dest = tmp_path / "umbrel" / "ais", tmp_path / "pc" / "ais"
    _recording(src, [10, 11], open_hour=12)
    res = pull(src.parent, dest, log=lambda m: None)  # the data folder or its ais/ both work
    assert sorted(res.copied) == ["ais-20261004-10.jsonl.gz", "ais-20261004-11.jsonl.gz",
                                  "rest/vessels-2026-10-04.json.gz"]
    assert res.open_hours == ["ais-20261004-12.jsonl"] and not res.errors and not res.conflicts
    assert (dest / "gaps-umbrel.jsonl").read_bytes() == (src / "gaps.jsonl").read_bytes()
    assert not list(dest.rglob("*.part"))
    assert verify(dest, now=ts(2026, 10, 4, 12, 0, 30), out=lambda m: None) == 0

    again = pull(src, dest, log=lambda m: None)
    assert again.copied == [] and again.skipped == 3


def test_pull_never_overwrites_and_rejects_corrupt_source(tmp_path):
    from alibi_recorder.pull import pull

    src, dest = tmp_path / "src", tmp_path / "dest"
    _recording(src, [10, 11])
    day = "2026/10/04"
    # dest already holds a different hour-10 file: must stay as it is
    (dest / day).mkdir(parents=True)
    (dest / day / "ais-20261004-10.jsonl.gz").write_bytes(b"mine")
    # source hour 11 got corrupted after its checksum was written
    bad = src / day / "ais-20261004-11.jsonl.gz"
    bad.write_bytes(bad.read_bytes()[:-3])
    res = pull(src, dest, log=lambda m: None)
    assert (dest / day / "ais-20261004-10.jsonl.gz").read_bytes() == b"mine"
    assert any("ais-20261004-10" in c for c in res.conflicts)
    assert any("ais-20261004-11" in e and "checksum" in e for e in res.errors)
    assert not (dest / day / "ais-20261004-11.jsonl.gz").exists()
    assert not list(dest.rglob("*.part"))
