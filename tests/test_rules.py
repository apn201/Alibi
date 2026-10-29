"""Rules on synthetic one-ship tracks: what must fire, what must stay quiet, and at which sensitivity."""

import re

import numpy as np
import pandas as pd

import rules

T0 = 1_700_000_000 // 60 * 60  # a whole minute


def track(sog, cog=90.0, lat=60.4, lon=22.0, step=60, t0=T0):
    """One report per `step` s. Position advances along the course at the given speed, so it is physical."""
    sog = np.asarray(sog, float)
    cog = np.broadcast_to(np.asarray(cog, float), sog.shape).copy()
    d_nm = sog * step / 3600
    la = lat + np.cumsum(d_nm * np.cos(np.radians(cog))) / 60
    lo = lon + np.cumsum(d_nm * np.sin(np.radians(cog))) / 60 / np.cos(np.radians(lat))
    return pd.DataFrame({"time": t0 + step * np.arange(len(sog)), "lat": la, "lon": lo, "sog": sog, "cog": cog,
                         "heading": cog})


def wobble(n, amp=0.1):
    return amp * np.sin(np.arange(n) * 0.9)


def types(events, kind=None):
    return [e["event_type"] for e in events if kind is None or e["event_type"] == kind]


def steady_then(level, cruise=12.0, before=120, after=40):
    return track(np.r_[cruise + wobble(before), level + wobble(after)])


def test_steady_cruise_is_quiet():
    t = track(12 + wobble(240))
    for s in (0, 0.5, 1):
        assert rules.detect(t, s) == []


def test_quarter_drop_flags_at_half_not_at_zero():
    t = steady_then(9.0)  # x0.75: not below 0.7, but far outside a steady ship's spread
    assert types(rules.detect(t, 0.0), "slowdown") == []
    ev = rules.detect(t, 0.5)
    sd = [e for e in ev if e["event_type"] == "slowdown"]
    assert len(sd) == 1
    b = sd[0]["baseline_summary"]
    assert b["rule"] == "sigma_4_and_10pct"
    assert abs(b["reference_kn"] - 12) < 0.3
    assert b["fingerprint"] == "steady_cruise_drop"  # steady hour, 25 % drop, course held
    assert rules._core._t(b["detected_at"]) - T0 < (120 + 15) * 60  # flagged within 15 min of the onset


def test_sensitivity_one_flags_no_later_than_half():
    t = steady_then(9.0)
    at = lambda s: rules._core._t([e for e in rules.detect(t, s) if e["event_type"] == "slowdown"][0]["baseline_summary"]["detected_at"])
    assert at(1.0) <= at(0.5)


def test_big_drop_flags_at_zero():
    t = steady_then(6.0)  # x0.5
    assert types(rules.detect(t, 0.0), "slowdown") == ["slowdown"]


def test_unsteady_or_slow_ship_is_not_judged():
    rng = np.random.default_rng(1)
    erratic = track(np.r_[rng.uniform(3, 14, 120), 4 + wobble(40)])
    assert types(rules.detect(erratic, 1.0), "slowdown") == []
    slow = track(np.r_[4 + wobble(120), 1 + wobble(40)])  # never cruising at 6 kn
    assert types(rules.detect(slow, 1.0), "slowdown") == []


def test_event_ids_are_deterministic_and_vocabulary_is_clean():
    t = steady_then(6.0)
    a, b = rules.detect(t, 0.5, mmsi=123), rules.detect(t, 0.5, mmsi=123)
    assert [e["event_id"] for e in a] == [e["event_id"] for e in b]
    assert rules.detect(t, 0.5, mmsi=124)[0]["event_id"] != a[0]["event_id"]
    assert a[0]["vessel_id"] == "123" and a[0]["start_time"].endswith("Z")
    for e in a:
        assert not re.search(r"threat|suspect|anchor|sabotage", str(e), re.I)


def grounding_track(erratic=True):
    """Anchorage, 30 min of turning about, 20 min straight at 11.6 kn, then 11.6 -> 0.5 kn in 3 min and stay."""
    rng = np.random.default_rng(3)
    sog = np.r_[np.full(30, 5.0), np.full(20, 11.6), [8, 3.5, 0.5], np.zeros(40)]
    wander = np.cumsum(rng.normal(0, 25, 30)) % 360 if erratic else np.full(30, 90.0)
    return track(sog, cog=np.r_[wander, np.full(len(sog) - 30, 180.0)], lat=55.9, lon=12.69)


def test_grounding_template():
    t = grounding_track()
    for s in (0.0, 0.5, 1.0):
        g = [e for e in rules.detect(t, s) if e["event_type"] == "grounding_pattern"]
        assert len(g) == 1, s
        assert g[0]["baseline_summary"]["erratic_before"] is True
        assert g[0]["baseline_summary"]["reference_kn"] > 11


def test_grounding_needs_an_abrupt_stop():
    # same run, but speed falls over 40 min: an ordinary arrival
    sog = np.r_[np.full(30, 5.0), np.full(20, 11.6), np.linspace(11.6, 0, 40), np.zeros(30)]
    t = track(sog, cog=180.0, lat=55.9, lon=12.69)
    assert types(rules.detect(t, 1.0), "grounding_pattern") == []


def test_stop_areas_silence_arrivals_at_low_tiers_only():
    t = grounding_track()
    cells = {rules._core.cell(la, lo) for la, lo in zip(t["lat"], t["lon"])}
    stops = {(i + a, j + b) for i, j in cells for a in (-1, 0, 1) for b in (-1, 0, 1)}
    assert types(rules.detect(t, 0.5, stops=stops), "grounding_pattern") == []
    assert types(rules.detect(t, 1.0, stops=stops), "grounding_pattern") == ["grounding_pattern"]


def gap_track():
    t = track(np.full(120, 10.0))
    return pd.concat([t.iloc[:60], t.iloc[85:]], ignore_index=True)  # 25 min of silence


def test_ais_gap_flags_a_moving_ship():
    ev = rules.detect(gap_track(), 0.5)
    g = [e for e in ev if e["event_type"] == "ais_gap"]
    assert len(g) == 1 and 24 < g[0]["baseline_summary"]["gap_min"] < 27
    assert types(rules.detect(gap_track(), 0.0), "ais_gap") == []  # conservative tier wants 30 min


def test_recorder_outage_is_not_a_dark_ship():
    t = gap_track()
    outage = (float(T0 + 61 * 60), float(T0 + 83 * 60))
    assert types(rules.detect(t, 0.5, outages=[outage]), "ais_gap") == []


def test_quiet_moored_ship_is_not_a_gap():
    t = track(np.full(120, 0.0))
    t = pd.concat([t.iloc[:60], t.iloc[90:]], ignore_index=True)
    assert types(rules.detect(t, 1.0), "ais_gap") == []


def test_corridor_loiter_and_crossing():
    # Estlink 2 passes (59.95 N, 26.10 E) in corridors.geojson
    loiter = track(np.full(45, 2.0), cog=90.0, lat=59.95, lon=26.09)
    ev = [e for e in rules.detect(loiter, 0.5) if e["event_type"] == "corridor_loiter"]
    assert len(ev) == 1 and ev[0]["baseline_summary"]["corridor_id"] == "estlink2"
    crossing = track(np.full(60, 12.0), cog=0.0, lat=59.60, lon=26.10 + 0.03)  # northbound across the line at cruise speed
    assert types(rules.detect(crossing, 1.0), "corridor_loiter") == []


def test_tiers_tag_the_lowest_firing_tier():
    ev = rules.detect_tiers(steady_then(9.0))
    sd = [e for e in ev if e["event_type"] == "slowdown"][0]
    assert sd["baseline_summary"]["min_tier"] == 1
    ev = rules.detect_tiers(steady_then(6.0))
    assert [e for e in ev if e["event_type"] == "slowdown"][0]["baseline_summary"]["min_tier"] == 0
