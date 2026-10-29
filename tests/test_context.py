import gzip
import json

from alibi_recorder import context as C
from alibi_recorder.pull import pull_context

HOUR = C.Source("warn", "http://x/warn", "hour")
DAY = C.Source("calls", "http://x/calls?date={yesterday}", "day")
T0 = 1791158400.0  # 2026-10-05 00:00 UTC


class FakeWeb:
    def __init__(self):
        self.body = {"http://x/warn": {"lastUpdated": "a", "features": [1]}}
        self.calls = []
        self.fail = False

    def __call__(self, url):
        self.calls.append(url)
        if self.fail:
            raise IOError("down")
        return json.dumps(self.body.get(url, {"day": url})).encode()


def index(root):
    return [json.loads(l) for l in (root / "index.jsonl").read_text().splitlines()]


def test_stores_once_per_change_and_records_unchanged(tmp_path):
    web, now = FakeWeb(), [T0]
    rec = C.ContextRecorder(tmp_path, [HOUR], fetcher=web, clock=lambda: now[0], log=lambda m: None)
    assert [e["status"] for e in rec.tick()] == ["stored"]
    assert rec.tick() == []  # same hour: nothing due
    now[0] += 3600
    web.body["http://x/warn"]["lastUpdated"] = "b"  # only the timestamp changed
    assert [e["status"] for e in rec.tick()] == ["unchanged"]
    now[0] += 3600
    web.body["http://x/warn"]["features"] = [1, 2]
    e = rec.tick()[0]
    assert e["status"] == "stored"
    stored = [x for x in index(tmp_path) if x["status"] == "stored"]
    assert len(stored) == 2
    assert json.loads(gzip.decompress((tmp_path / e["file"]).read_bytes()))["features"] == [1, 2]


def test_error_waits_before_retrying_and_daily_source_asks_for_yesterday(tmp_path):
    web, now = FakeWeb(), [T0 + 7200]
    rec = C.ContextRecorder(tmp_path, [HOUR, DAY], fetcher=web, clock=lambda: now[0], log=lambda m: None)
    web.fail = True
    assert {e["status"] for e in rec.tick()} == {"error"}
    now[0] += 60
    assert rec.tick() == []  # within RETRY_S: leave the source alone
    web.fail = False
    now[0] += C.RETRY_S
    assert {e["status"] for e in rec.tick()} == {"stored"}
    assert "http://x/calls?date=2026-10-04" in web.calls


def test_state_survives_restart_and_pull_copies_verified(tmp_path):
    web, now = FakeWeb(), [T0]
    src = tmp_path / "umbrel" / "context"
    C.ContextRecorder(src, [HOUR], fetcher=web, clock=lambda: now[0], log=lambda m: None).tick()
    again = C.ContextRecorder(src, [HOUR], fetcher=web, clock=lambda: now[0], log=lambda m: None)
    assert again.tick() == []  # restart in the same hour: already done
    now[0] += 3600
    assert again.tick()[0]["status"] == "unchanged"  # remembers the last content

    dest = tmp_path / "pc" / "context"
    res = pull_context(src, dest, log=lambda m: None)
    assert len(res.copied) == 1 and not res.errors
    assert (dest / "index-umbrel.jsonl").read_bytes() == (src / "index.jsonl").read_bytes()
    assert pull_context(src, dest, log=lambda m: None).skipped == 1


def test_extraction_dates_inside_features_do_not_count_as_change():
    a = {"type": "FeatureCollection", "timeStamp": "1", "features": [{"properties": {"id": 1, "irrotus_pvm": "2026-10-18"}}]}
    b = {"type": "FeatureCollection", "timeStamp": "2", "features": [{"properties": {"id": 1, "irrotus_pvm": "2026-10-19"}}]}
    c = {"type": "FeatureCollection", "timeStamp": "2", "features": [{"properties": {"id": 2, "irrotus_pvm": "2026-10-19"}}]}
    h = lambda d: C.content_hash(json.dumps(d).encode())
    assert h(a) == h(b) != h(c)
