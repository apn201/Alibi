import numpy as np
import pandas as pd

from alibi_lab import profiles as P


def track(speeds_kn, start=0, step_s=10, mmsi=1):
    n = len(speeds_kn)
    return pd.DataFrame({"mmsi": mmsi, "time": start + np.arange(n) * step_s, "sog": speeds_kn,
                         "lat": 60.0, "lon": 24.0, "cog": 90.0, "heading": 90.0})


def store_with(proto_speed=12.0, own=None):
    """A store with one prototype class 'cargo/L' and optionally an own profile for mmsi 1."""
    proto = P.Profile("cargo/L", 50.0, 20, {"speed": proto_speed}, {"speed": 4.0})
    vessels = {} if own is None else {1: P.Profile("1", own[1], 5, {"speed": own[0]}, {})}
    return P.ProfileStore({"cargo/L": proto, "*/*": proto}, vessels, {1: "cargo/L"})


def windows(df, minutes=10):
    for t0 in range(int(df["time"].min()), int(df["time"].max()), minutes * 60):
        yield df[(df["time"] >= t0) & (df["time"] < t0 + minutes * 60)]


def test_tiers_follow_own_hours():
    assert store_with().tier(1) == "new"
    assert store_with(own=(10, 2.0)).tier(1) == "rare"
    assert store_with(own=(10, 30.0)).tier(1) == "frequent"


def test_new_ship_journey_takes_over_from_prototype():
    s = store_with(proto_speed=15.0)
    cold = s.expected(1)["speed"]
    one_hour = s.expected(1, journey=P.Profile("j", 1.0, 1, {"speed": 9.0}, {}))["speed"]
    assert cold == 15.0
    assert abs(one_hour - 9.0) < 0.6  # journey primary within the hour


def test_frequent_ship_own_profile_stays_in_charge():
    s = store_with(proto_speed=15.0, own=(20.0, 30.0))
    e = s.expected(1, journey=P.Profile("j", 5.0, 1, {"speed": 10.0}, {}))["speed"]
    assert e > 17.0  # own 20 kn dominates a few hours of a slower journey


def test_lasting_slowdown_is_flagged_and_not_learnt():
    s = store_with(proto_speed=12.0)
    tr = P.JourneyTracker(s, 1, 0)
    df = track([12.0] * 240 + [4.0] * 1080)  # 40 min cruise, then 3 h at a third of the speed
    flags = [tr.check(w)[1] for w in windows(df)]
    assert not any(flags[:4])
    assert all(flags[4:])  # still flagged hours later: the slowdown never became "normal"
    assert tr.journey().value["speed"] == 12.0


def test_ship_slower_than_its_class_is_not_locked_into_alarm():
    s = store_with(proto_speed=20.0)  # class cruises at 20, this ship steadily at 12
    tr = P.JourneyTracker(s, 1, 0)
    flags = [tr.check(w)[1] for w in windows(track([12.0] * 1440))]
    assert flags[0]  # cold start: only the class to compare with
    assert not any(flags[3:])  # the journey has taken over


def test_absorbing_tracker_forgets_a_slowdown():
    s = store_with(proto_speed=12.0)
    tr = P.JourneyTracker(s, 1, 0, use_own=None, absorb=True)
    flags = [tr.check(w)[1] for w in windows(track([12.0] * 240 + [4.0] * 1080))]
    assert flags[4] and not flags[-1]  # why freezing exists


def test_sigma_rule_catches_a_modest_drop_on_a_steady_ship():
    """Eagle S pattern: hours at a steady 12 kn, then ~9 kn (x0.75) - below the 0.7 ratio."""
    s = store_with(proto_speed=12.0)
    steady = track(list(12.0 + 0.1 * np.sin(np.arange(2160))) + [9.0] * 360)  # 6 h steady, then 1 h slower
    ratio = P.JourneyTracker(s, 1, 0, flag_below=0.7)
    sigma = P.JourneyTracker(s, 1, 0, flag_below=0.7, k_sigma=4.0, and_below=0.9)
    r = [ratio.check(w)[1] for w in windows(steady)]
    g = [sigma.check(w)[1] for w in windows(steady)]
    assert not any(r) and not any(g[:36])
    assert all(g[36:])


def test_sigma_rule_tolerates_an_erratic_ship():
    s = store_with(proto_speed=8.0)
    rng = np.random.default_rng(1)
    erratic = track(list(np.repeat(rng.uniform(5, 11, 36), 60)))  # window medians jump 5..11 kn
    sigma = P.JourneyTracker(s, 1, 0, flag_below=0.5, k_sigma=4.0, and_below=0.9)
    flags = [sigma.check(w)[1] for w in windows(erratic)]
    assert sum(flags[3:]) <= 2  # its own spread is wide: ordinary swings are not alarms
