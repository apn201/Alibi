"""Hierarchical behaviour profiles: prototype -> own long-term profile -> current journey.

Three sources of "what is normal for this ship right now", each with an amount of
evidence (hours of moving observation):

    prototype   ship class template: type group x length class. Always available.
    own         this vessel's history. Primary for frequent ships.
    journey     this vessel's current transit so far. Primary for ships never seen before.

Blend (per feature): a precision-weighted mean in which each source counts by its
hours, with the prototype and own profile capped so a long history cannot drown out
what the ship is doing today:

    w_proto = K_PROTO, w_own = min(h_own, CAP_OWN), w_journey = h_journey * JOURNEY_GAIN[tier]
    expected = sum(w * value) / sum(w)

A frequent ship's own profile outweighs its prototype after a few hours; a new ship's
journey outweighs the prototype after K_PROTO / JOURNEY_GAIN["new"] hours (6 min). All constants
are first guesses, set to be tuned on more data (see lab/02_prototypes.py).

Features, per moving segment (sog >= 2 kn, split at 15 min gaps or 10 min stops):
    speed      median sog, kn                     -> cruise speed
    speed_iqr  p75 - p25 of sog, kn               -> how steady
    crab       median |heading - cog|, deg (sog > 5) -> drift angle; weather-sensitive later
    turn       median |d cog| per minute, deg/min -> how much it manoeuvres
Profiles are location-free for now. Tile context comes in later as another factor.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

FEATURES = ["speed", "speed_iqr", "crab", "turn"]
MOVING_KN = 2.0
GAP_S = 900
STOP_S = 600
MIN_SEG_MIN = 10

K_PROTO = 2.0  # the prototype counts like this many hours of a ship's own data
CAP_OWN = 24.0  # own history counts at most this many hours
# An hour of the current journey counts like this many hours of history. Tier-dependent
# (lab 02): for a ship with no history the journey is the best evidence there is; for a
# frequent ship (ferry) its own profile already knows the trip, and the first minutes of
# a journey (leaving port, accelerating) are a poor guide to the rest.
JOURNEY_GAIN = {"new": 20.0, "rare": 20.0, "frequent": 0.5}
# The journey's weight is capped only where an own profile should stay in charge. For a
# ship with little or no history the prototype is a cold start, and fades as the journey
# grows (lab 02: keeping it mixed in tripled false alarms for new ships).
CAP_JOURNEY = {"new": float("inf"), "rare": float("inf"), "frequent": 8.0}
# Own moving hours from which a ship "has its own profile". A stand-in while there is
# one day of data: the intent is "seen again and again" (repeat journeys on several days).
FREQUENT_HOURS = 6.0
SCALE_FLOOR_KN = 0.3  # a ship's speed is never treated as steadier than this

LENGTH_CLASSES = [(0, 50, "S"), (50, 120, "M"), (120, 200, "L"), (200, 1e9, "XL")]


# -- segments and features -------------------------------------------------------------

def segments(loc: pd.DataFrame) -> pd.DataFrame:
    """Moving segments per vessel with their features. loc sorted by mmsi, time."""
    d = loc.dropna(subset=["lat", "lon", "sog"])
    out = []
    for mmsi, g in d.groupby("mmsi", sort=False):
        t = g["time"].to_numpy()
        moving = g["sog"].to_numpy() >= MOVING_KN
        # a segment breaks at a reporting gap, or at a stationary run of >= STOP_S
        seg = np.zeros(len(t), dtype=np.int64)
        sid, last_moving_t, still_since = 0, None, None
        for i in range(len(t)):
            if moving[i]:
                if last_moving_t is not None and (t[i] - last_moving_t > GAP_S or
                                                  (still_since is not None and t[i] - still_since >= STOP_S)):
                    sid += 1
                last_moving_t, still_since = t[i], None
                seg[i] = sid
            else:
                if still_since is None:
                    still_since = t[i]
                seg[i] = -1
        gm = g.assign(seg=seg)[seg >= 0]
        for s, h in gm.groupby("seg"):
            dur = (h["time"].iloc[-1] - h["time"].iloc[0]) / 60
            if dur < MIN_SEG_MIN or len(h) < 10:
                continue
            row = {"mmsi": mmsi, "seg": int(s), "t0": int(h["time"].iloc[0]), "t1": int(h["time"].iloc[-1]),
                   "minutes": dur, "n": len(h),
                   "lat": float(h["lat"].median()), "lon": float(h["lon"].median())}
            row.update(features(h))
            if "draught" in h:  # load, from DMA positions (m); not in the Digitraffic location stream
                row["draught"] = float(h["draught"].median()) if h["draught"].notna().any() else np.nan
            out.append(row)
    return pd.DataFrame(out)


def features(h: pd.DataFrame) -> dict:
    sog = h["sog"].to_numpy()
    fast = h[(h["sog"] > 5) & h["heading"].notna() & h["cog"].notna()]
    crab = np.abs((fast["heading"] - fast["cog"] + 180) % 360 - 180)
    cog = h["cog"].to_numpy()
    dt = np.diff(h["time"].to_numpy()) / 60
    dc = np.abs((np.diff(cog) + 180) % 360 - 180)
    ok = (dt > 0) & ~np.isnan(dc)
    return {
        "speed": float(np.median(sog)),
        "speed_iqr": float(np.quantile(sog, 0.75) - np.quantile(sog, 0.25)),
        "crab": float(np.median(crab)) if len(crab) >= 5 else np.nan,
        "turn": float(np.median(dc[ok] / dt[ok])) if ok.sum() >= 5 else np.nan,
    }


# -- classes -----------------------------------------------------------------------------

def ship_class(vessels: pd.DataFrame) -> pd.Series:
    """mmsi -> prototype key like 'cargo/L'. Length = refA + refB (m), 0 means unknown."""
    length = pd.to_numeric(vessels["refA"], errors="coerce") + pd.to_numeric(vessels["refB"], errors="coerce")
    length = length.where(length > 0)
    size = pd.Series("?", index=vessels.index)
    for lo, hi, label in LENGTH_CLASSES:
        size[(length >= lo) & (length < hi)] = label
    return vessels["group"].astype(str) + "/" + size


# -- profiles ----------------------------------------------------------------------------

@dataclass
class Profile:
    """Feature summary of some moving segments: hours-weighted median and spread."""
    key: str
    hours: float
    segments: int
    value: dict = field(default_factory=dict)  # feature -> typical value
    spread: dict = field(default_factory=dict)  # feature -> p90 - p10 across segments

    @classmethod
    def fit(cls, key: str, segs: pd.DataFrame) -> "Profile":
        w = segs["minutes"].to_numpy()
        value, spread = {}, {}
        for f in FEATURES:
            x = segs[f].to_numpy()
            ok = ~np.isnan(x)
            if ok.sum() == 0:
                continue
            value[f] = _wquantile(x[ok], w[ok], 0.5)
            spread[f] = _wquantile(x[ok], w[ok], 0.9) - _wquantile(x[ok], w[ok], 0.1) if ok.sum() >= 3 else np.nan
        return cls(key, float(w.sum() / 60), len(segs), value, spread)


def _wquantile(x: np.ndarray, w: np.ndarray, q: float) -> float:
    order = np.argsort(x)
    x, w = x[order], w[order]
    c = np.cumsum(w) - 0.5 * w
    return float(np.interp(q * w.sum(), c, x))


@dataclass
class ProfileStore:
    prototypes: dict[str, Profile]
    vessels: dict[int, Profile]
    vessel_class: dict[int, str]
    fitted_until: int | None = None

    @classmethod
    def fit(cls, segs: pd.DataFrame, classes: pd.Series, until: int | None = None) -> "ProfileStore":
        if until is not None:
            segs = segs[segs["t1"] < until]
        segs = segs.assign(cls=segs["mmsi"].map(classes).fillna("unknown/?"))
        protos = {k: Profile.fit(k, g) for k, g in segs.groupby("cls")}
        # broader fallbacks for rare classes: type group only, then everything
        for grp, g in segs.groupby(segs["cls"].str.split("/").str[0]):
            protos[f"{grp}/*"] = Profile.fit(f"{grp}/*", g)
        protos["*/*"] = Profile.fit("*/*", segs)
        own = {int(m): Profile.fit(str(m), g) for m, g in segs.groupby("mmsi")}
        return cls(protos, own, {int(k): v for k, v in classes.items()}, until)

    def prototype_for(self, mmsi: int, min_hours: float = 3.0) -> Profile:
        key = self.vessel_class.get(int(mmsi), "unknown/?")
        for k in (key, key.split("/")[0] + "/*", "*/*"):
            p = self.prototypes.get(k)
            if p is not None and p.hours >= min_hours:
                return p
        return self.prototypes["*/*"]

    def expected(self, mmsi: int, journey: Profile | None = None, use_own: bool = True) -> dict:
        """Blend prototype, own profile and current journey -> {feature: (value, weights)}."""
        sources = [(self.prototype_for(mmsi), K_PROTO)]
        own = self.vessels.get(int(mmsi)) if use_own else None
        if own is not None:
            sources.append((own, min(own.hours, CAP_OWN)))
        if journey is not None:
            tier = self.tier(mmsi) if use_own else "new"
            sources.append((journey, min(journey.hours * JOURNEY_GAIN[tier], CAP_JOURNEY[tier])))
        out = {}
        for f in FEATURES:
            vals = [(p.value[f], w) for p, w in sources if f in p.value and not np.isnan(p.value[f])]
            if vals:
                v, w = np.array(vals).T
                out[f] = float((v * w).sum() / w.sum())
        return out

    def tier(self, mmsi: int) -> str:
        own = self.vessels.get(int(mmsi))
        if own is None:
            return "new"
        return "frequent" if own.hours >= FREQUENT_HOURS else "rare"

    def save(self, path: Path) -> None:
        """Templates on disk: the prototypes (and own profiles) as JSON, to grow with more data."""
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = {"fitted_until": self.fitted_until,
               "constants": {"K_PROTO": K_PROTO, "CAP_OWN": CAP_OWN, "JOURNEY_GAIN": JOURNEY_GAIN, "CAP_JOURNEY": CAP_JOURNEY,
                             "FREQUENT_HOURS": FREQUENT_HOURS},
               "prototypes": {k: asdict(p) for k, p in sorted(self.prototypes.items())},
               "vessels": {str(k): asdict(p) for k, p in self.vessels.items()},
               "vessel_class": {str(k): v for k, v in self.vessel_class.items()}}
        path.write_text(json.dumps(doc, indent=1, default=float), encoding="utf-8")


# -- evaluation ----------------------------------------------------------------------------

def evaluate(loc: pd.DataFrame, segs: pd.DataFrame, classes: pd.Series, split: int,
             step_min: float = 20.0, horizon_min: float = 30.0) -> tuple[ProfileStore, pd.DataFrame]:
    """Fit on everything before `split`. Then walk each later segment as if live: every
    `step_min` minutes, predict the features of the next `horizon_min` minutes from
    what is known at that moment (profiles + the journey so far).

    Returns (store, table): one row per checkpoint and feature, with the target and the
    prediction of each strategy:
        proto    prototype only
        own      own history only (NaN when the ship has none)
        history  prototype + own (what we know before the ship sets off)
        journey  the journey so far only
        blend    prototype + own + journey (the hierarchy)
    """
    store = ProfileStore.fit(segs, classes, until=split)
    test = segs[(segs["t0"] >= split) & (segs["minutes"] >= step_min + horizon_min / 2)]
    by_ship = {m: g for m, g in loc[loc["mmsi"].isin(test["mmsi"].unique())].groupby("mmsi")}
    rows = []
    for seg in test.itertuples():
        pts = by_ship[seg.mmsi]
        pts = pts[(pts["time"] >= seg.t0) & (pts["time"] <= seg.t1) & (pts["sog"] >= MOVING_KN)]
        tier = store.tier(seg.mmsi)
        proto = store.prototype_for(seg.mmsi)
        cut = seg.t0 + step_min * 60
        while cut < seg.t1 - 60 * horizon_min / 2:
            head = pts[pts["time"] < cut]
            nxt = pts[(pts["time"] >= cut) & (pts["time"] < cut + horizon_min * 60)]
            if len(head) >= 5 and len(nxt) >= 10:
                journey = Profile(f"{seg.mmsi}@journey", (cut - seg.t0) / 3600, 1, features(head), {})
                target = features(nxt)
                preds = {
                    "proto": proto.value,
                    "own": store.vessels[seg.mmsi].value if seg.mmsi in store.vessels else {},
                    "history": store.expected(seg.mmsi),
                    "journey": journey.value,
                    "blend": store.expected(seg.mmsi, journey=journey),
                }
                for f in FEATURES:
                    if np.isnan(target.get(f, np.nan)):
                        continue
                    row = {"mmsi": seg.mmsi, "seg": seg.seg, "tier": tier, "cls": proto.key,
                           "journey_min": (cut - seg.t0) / 60, "feature": f, "target": target[f]}
                    for k, p in preds.items():
                        row[k] = p.get(f, np.nan)
                    rows.append(row)
            cut += step_min * 60
    return store, pd.DataFrame(rows)


class JourneyTracker:
    """Live, per vessel and journey: what is this ship doing compared with what is normal?

    Each window of new positions is judged against the blend of prototype, own profile
    and the journey so far. A window that looks normal is then learnt into the journey;
    a flagged one is not, so a lasting change cannot teach itself to look normal
    (lab 02: without this, a slowdown is forgotten within an hour).
    `absorb=True` learns every window regardless, for comparison.

    How far below is "too slow": with `k_sigma` set, a drop counts in units of the ship's
    own steadiness on this journey (robust spread of its learnt window medians, at least
    SCALE_FLOOR_KN); before 3 windows are learnt, and without `k_sigma`, the fixed ratio
    `flag_below` is used. Lab 03: Eagle S fell from a steady 12 kn to ~9 kn (x0.75) while
    crossing the cables, which a fixed x0.7 rule misses for 45 minutes.
    """

    def __init__(self, store: ProfileStore, mmsi: int, t0: int, flag_below: float = 0.7,
                 use_own: bool = True, use_journey: bool = True, absorb: bool = False,
                 k_sigma: float | None = None, and_below: float | None = None):
        self.store, self.mmsi, self.t0 = store, int(mmsi), t0
        self.flag_below, self.use_own, self.use_journey, self.absorb = flag_below, use_own, use_journey, absorb
        self.k_sigma, self.and_below = k_sigma, and_below
        self.speeds: list[np.ndarray] = []
        self.window_medians: list[float] = []
        self.hours = 0.0

    def scale(self) -> float | None:
        """The ship's own window-to-window speed variability on this journey, kn."""
        if len(self.window_medians) < 3:
            return None
        m = np.asarray(self.window_medians)
        return max(1.4826 * float(np.median(np.abs(m - np.median(m)))), SCALE_FLOOR_KN)

    def too_slow(self, observed: float, reference: float | None) -> bool:
        if reference is None or np.isnan(reference):
            return False
        # A big drop is always too slow (robust for erratic ships, whose spread is wide).
        big = observed < self.flag_below * reference
        scale = self.scale() if self.k_sigma is not None else None
        if scale is None:
            return big
        # A smaller drop is too slow when it is unusual for this ship's own steadiness and
        # still large enough to matter (and_below): catches steady ships early (Eagle S).
        unusual = observed < reference - self.k_sigma * scale
        return big or (unusual and (self.and_below is None or observed < self.and_below * reference))

    def journey(self) -> Profile | None:
        if not self.use_journey or not self.speeds:
            return None
        return Profile("journey", self.hours, 1, {"speed": float(np.median(np.concatenate(self.speeds)))}, {})

    def expected_speed(self) -> float | None:
        if self.use_own is None:  # journey only
            j = self.journey()
            return None if j is None else j.value["speed"]
        return self.store.expected(self.mmsi, journey=self.journey(), use_own=self.use_own).get("speed")

    def learn(self, window: pd.DataFrame) -> None:
        self.speeds.append(window["sog"].to_numpy())
        self.window_medians.append(float(window["sog"].median()))
        self.hours += (window["time"].iloc[-1] - window["time"].iloc[0]) / 3600

    def check(self, window: pd.DataFrame) -> tuple[float | None, bool]:
        """Judge one window, then learn it unless the ship changed. Returns (expected, flagged).

        Reporting and learning are separate decisions (lab 02). The flag compares with the
        full blend. Learning is held back only when the ship departs from its *own journey*
        so far: a ship that is merely slower than its class has not changed, and freezing
        on that locked a single early false alarm in for the rest of the journey.
        """
        expected = self.expected_speed()
        observed = float(window["sog"].median())
        flagged = self.too_slow(observed, expected)
        journey = self.journey()
        changed = journey is not None and self.too_slow(observed, journey.value["speed"])
        if self.absorb or not changed:
            self.learn(window)
        return expected, flagged


def slowdown_test(loc: pd.DataFrame, store: ProfileStore, segs: pd.DataFrame, split: int,
                  factor: float = 0.4, onset_min: float = 40.0, flag_below: float = 0.7,
                  window_min: float = 10.0, strategies: dict | None = None) -> pd.DataFrame:
    """Does each strategy notice a ship that slows down and stays slow?

    For each later segment long enough, two runs over the same real track: as recorded
    ("normal"), and with sog multiplied by `factor` from `onset_min` on ("slowdown", the
    dragging-anchor pattern). Each strategy is a JourneyTracker fed the track window by
    window (`window_min`) from the segment start, exactly as it would run live; windows
    from onset on are scored. Rows: segment, case, minutes since onset, strategy, flagged.
    """
    strategies = strategies or {
        "proto": dict(use_own=False, use_journey=False),
        "history": dict(use_own=True, use_journey=False),
        "journey (absorbing)": dict(use_own=None, absorb=True),
        "journey (frozen)": dict(use_own=None, absorb=False),
        "blend (absorbing)": dict(use_own=True, absorb=True),
        "blend (frozen)": dict(use_own=True, absorb=False),
    }
    test = segs[(segs["t0"] >= split) & (segs["minutes"] >= onset_min + 60)]
    by_ship = {m: g for m, g in loc[loc["mmsi"].isin(test["mmsi"].unique())].groupby("mmsi")}
    slow_kn = MOVING_KN * factor  # same "still moving" threshold for both runs
    rows = []
    for seg in test.itertuples():
        pts = by_ship[seg.mmsi]
        pts = pts[(pts["time"] >= seg.t0) & (pts["time"] <= seg.t1)]
        onset = seg.t0 + onset_min * 60
        tier = store.tier(seg.mmsi)
        for case in ("normal", "slowdown"):
            sog = pts["sog"].to_numpy().copy()
            if case == "slowdown":
                sog[pts["time"].to_numpy() >= onset] *= factor
            p = pts.assign(sog=sog)
            p = p[p["sog"] >= slow_kn]
            trackers = {k: JourneyTracker(store, seg.mmsi, seg.t0, **{"flag_below": flag_below, **kw})
                        for k, kw in strategies.items()}
            cut = seg.t0
            while cut + window_min * 60 <= seg.t1:
                window = p[(p["time"] >= cut) & (p["time"] < cut + window_min * 60)]
                if len(window) >= 5:
                    for k, tr in trackers.items():
                        expected, flagged = tr.check(window)
                        if cut >= onset and expected is not None and not np.isnan(expected):
                            rows.append({"mmsi": seg.mmsi, "seg": seg.seg, "tier": tier, "case": case,
                                         "since_onset_min": (cut - onset) / 60, "strategy": k,
                                         "flagged": flagged, "lat": float(window["lat"].median()),
                                         "lon": float(window["lon"].median())})
                cut += window_min * 60
    return pd.DataFrame(rows)


def replay(track: pd.DataFrame, store: ProfileStore, mmsi: int, strategies: dict,
           window_min: float = 10.0, start: int | None = None, end: int | None = None) -> pd.DataFrame:
    """Run JourneyTrackers over one ship's track window by window, as live.

    track: time, sog (and anything else) for one vessel. Returns one row per window and
    strategy: t (window start), observed median sog, expected, flagged."""
    t = track[(track["sog"] >= 0)]
    if start is not None:
        t = t[t["time"] >= start]
    if end is not None:
        t = t[t["time"] < end]
    trackers = {k: JourneyTracker(store, mmsi, int(t["time"].iloc[0]), **kw) for k, kw in strategies.items()}
    rows, cut = [], int(t["time"].iloc[0])
    while cut < t["time"].iloc[-1]:
        w = t[(t["time"] >= cut) & (t["time"] < cut + window_min * 60)]
        if len(w) >= 5:
            for k, tr in trackers.items():
                expected, flagged = tr.check(w)
                rows.append({"t": cut, "strategy": k, "observed": float(w["sog"].median()),
                             "expected": expected, "flagged": flagged, "scale": tr.scale()})
        cut += int(window_min * 60)
    return pd.DataFrame(rows)
