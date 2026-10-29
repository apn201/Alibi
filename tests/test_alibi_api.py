"""ALIBI API: contract, scoring invariants and error codes, through FastAPI's TestClient.

Needs the profile DB under data/ (git-ignored); skipped where it is missing.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(not (ROOT / "data" / "derived" / "profile_db" / "vessel_profiles.parquet").exists(),
                                reason="profile DB not present")
EXAMPLE = ROOT / "examples" / "event-eagle-like.json"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    from fastapi.testclient import TestClient

    from alibi import config
    config.LEDGER = tmp_path_factory.mktemp("ledger") / "ledger.sqlite"
    from alibi.api import app
    with TestClient(app) as c:
        yield c


def synthetic(lat=45.0, lon=-20.0, start="2026-10-26T04:00:00Z", fast=12.0, slow=3.0, n=360, onset=300, **meta):
    t0 = datetime.fromisoformat(start.replace("Z", "+00:00"))
    track = [{"timestamp": (t0 + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ"), "latitude": lat,
              "longitude": lon + i * 0.003, "sog_knots": fast if i < onset else slow, "cog_degrees": 90.0}
             for i in range(n)]
    event = {"event_id": "syn-1", "event_type": "slowdown", "start_time": track[onset]["timestamp"],
             "end_time": track[-1]["timestamp"]}
    return {"event": event, "track": track, "metadata": {"ship_type": "Cargo", "length_m": 150, **meta}}


def post(client, body, path="/api/v1/assessments"):
    return client.post(path, json=body)


def behaviour(findings):
    return [f for f in findings if f["source_id"] not in ("position_quality", "identity")]


def test_health_and_sources(client):
    h = client.get("/api/v1/health").json()
    assert h["api_version"] == "1.0.0" and h["status"] in ("ok", "degraded")
    assert {"profiles", "ledger", "envcache"} <= set(h["dependencies"])
    assert h["dependencies"]["profiles"] in ("ok", "degraded")
    ids = [s["id"] for s in client.get("/api/v1/sources").json()]
    assert ids == ["profile", "sea_state", "ice", "own_habit", "place", "fleet", "notices", "position_quality", "identity"]
    assert client.get("/api/v1/openapi.yaml").text.startswith("openapi:")
    assert client.get("/api/v1/openapi.json").status_code == 200


def test_synthetic_slowdown_unexplained_equals_unusual(client):
    """Mid-Atlantic: outside every data source, so nothing explains and X == U."""
    r = post(client, synthetic())
    assert r.status_code == 200, r.text
    a = r.json()
    m = a["measures"]
    assert m["unusual"] > 0.9
    assert all(f["explains"] == 0 for f in behaviour(a["findings"]))
    assert m["unexplained"] == pytest.approx(m["unusual"])
    assert m["band"] == "top"
    assert a["headline"] == "Behaving unusually, and the available evidence does not explain it."
    assert a["configuration"]["detected_by"] == "upstream"
    assert a["configuration"]["profile_version"] == "pdb-2026-10-28"
    sig = a["signature"]
    n = len(sig["t"])
    assert n > 300 and all(len(sig[k]) == n for k in ("observed_kn", "expected_profile_kn", "band_profile_kn",
                                                      "expected_adjusted_kn", "band_adjusted_kn", "state"))
    assert sig["state"][-1] == 2 and sig["state"][0] == 0
    assert set(a["lamps"]) == {"WX", "ICE", "PLC", "GNSS", "TRF"}


def test_unavailable_lowers_confidence(client):
    covered = post(client, synthetic(lat=59.65, lon=24.3)).json()
    outside = post(client, synthetic()).json()
    rank = {"high": 2, "medium": 1, "low": 0}
    assert outside["details"]["confidence_penalty"] > covered["details"]["confidence_penalty"]
    assert rank[outside["confidence"]["level"]] <= rank[covered["confidence"]["level"]]
    assert any(f["status"] == "unavailable" for f in outside["findings"])


def test_x_never_exceeds_u_and_identity_never_changes_x(client):
    body = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    with_id = post(client, body).json()
    body["options"] = {"enabled_sources": [s for s in with_id["configuration"]["enabled_sources"] if s != "identity"]}
    without = post(client, body).json()
    assert with_id["measures"]["unexplained"] == without["measures"]["unexplained"]
    assert with_id["measures"]["unexplained"] <= with_id["measures"]["unusual"]
    ident = [f for f in with_id["findings"] if f["source_id"] == "identity"][0]
    assert ident["status"] == "identity_context_only"
    # an EU-designated IMO: shown as context, X unchanged
    syn = synthetic(imo=9179842)
    a = post(client, syn).json()
    syn["options"] = {"enabled_sources": ["sea_state", "own_habit", "place", "fleet", "notices", "position_quality"]}
    b = post(client, syn).json()
    ident = [f for f in a["findings"] if f["source_id"] == "identity"][0]
    assert ident["details"]["eu_designation"]["listed"] is True
    assert "sanctioned" not in ident["summary"].lower()
    assert a["measures"]["unexplained"] == b["measures"]["unexplained"]


def test_example_is_fast_and_recorded(client):
    body = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    post(client, body)
    t = time.perf_counter()
    r = post(client, body)
    elapsed = time.perf_counter() - t
    assert r.status_code == 200
    assert elapsed < 1.0  # target 0.3 s; generous for slow CI disks
    a = r.json()
    assert a["vessel"]["profile_tier"] in ("own", "journey", "prototype")
    assert a["audit_reference"].endswith(a["assessment_id"])
    got = client.get(f"/api/v1/assessments/{a['assessment_id']}")
    assert got.status_code == 200 and got.json()["assessment_id"] == a["assessment_id"]
    assert client.get("/api/v1/assessments/asm_nope").status_code == 404


def test_track_mode(client):
    body = synthetic()
    body.pop("event")
    a = post(client, body).json()
    assert a["configuration"]["detected_by"] == "reference_detector"
    assert a["measures"]["unusual"] > 0.5


def test_working_vessel_not_scored(client):
    a = post(client, synthetic(ship_type="Tug", length_m=30)).json()
    assert a["vessel"]["profile_tier"] == "working"
    assert a["measures"]["unusual"] is None and a["measures"]["unexplained"] is None
    assert a["measures"]["band"] == "not_scored"


def test_errors(client):
    r = post(client, {"event": synthetic()["event"]})
    assert r.status_code == 400 and r.json()["error"] == "invalid_request"
    bad = synthetic()
    bad["track"][0]["latitude"] = 123
    assert post(client, bad).status_code == 400
    unknown = synthetic()
    unknown["options"] = {"enabled_sources": ["horoscope"]}
    assert post(client, unknown).status_code == 400
    short = synthetic(n=5, onset=3)
    r = post(client, short)
    assert r.status_code == 422 and r.json()["error"] == "track_too_short"
    gap = synthetic()
    gap["event"]["start_time"], gap["event"]["end_time"] = "2027-01-01T00:00:00Z", "2027-01-01T01:00:00Z"
    assert post(client, gap).status_code == 422
    r = client.post("/api/v1/assessments", content=b"{" + b" " * (6 * 1024 * 1024) + b"}",
                    headers={"content-type": "application/json"})
    assert r.status_code == 413 and r.json()["error"] == "payload_too_large"


def test_batch(client):
    body = {"requests": [synthetic(), synthetic(n=5, onset=3)],
            "options": {"enabled_sources": ["own_habit"], "sensitivity": 0.9}, "persist": False}
    r = client.post("/api/v1/assessments/batch", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert len(out) == 2
    assert out[0]["configuration"]["enabled_sources"] == ["profile", "own_habit"]
    assert out[0]["configuration"]["sensitivity"] == 0.9
    assert out[0]["audit_reference"] is None
    assert out[1]["index"] == 1 and out[1]["error"] == "track_too_short"
    assert client.get(f"/api/v1/assessments/{out[0]['assessment_id']}").status_code == 404
