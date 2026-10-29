"""One assessment: request in, Assessment out. No LLM anywhere; every sentence is fixed.

    1. track JSON -> DataFrame (time epoch s, lat, lon, sog, cog, heading, pos_acc, raim)
    2. the event: from the caller (event mode), or found by the reference detector over the
       track (track mode: `rules.detect` when that package provides it, else the lab-03 rule
       pair built in below). Several events: the most significant is assessed, the rest listed.
    3. Unusual (alibi.unusual) against the profile blend, unless the ship is a working vessel
    4. every enabled explainer -> Finding; Unexplained X = U x prod(1 - e) over behaviour findings
    5. confidence, lamps, the signature trace for the GUI, fixed limitations

Raises Unassessable (-> HTTP 422) when the track cannot carry an assessment.
"""

from __future__ import annotations

import math
import time
import uuid
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import API_VERSION, MODEL_VERSION, config, profiles, unusual as U
from .explainers import registry
from .explainers._util import iso
from .explainers.base import Context, Finding
from .schemas import AssessmentOptions, AssessmentRequest


class Unassessable(Exception):
    def __init__(self, error: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.error, self.message, self.details = error, message, details or {}


class BadRequest(Unassessable):
    pass


HEADLINES = {
    "top": "Behaving unusually, and the available evidence does not explain it.",
    "part": "Behaving unusually; the available evidence explains part of it.",
    "most": "Behaving unusually; the available evidence explains most of it.",
    "usual": "Not clearly unusual against this ship's expected behaviour.",
    "working": "Working vessel: its behaviour is not scored.",
    "unknown": "No expected speed could be formed for this ship, so it is not scored.",
}
LIMITATIONS = [
    "History: our own Gulf of Finland recording spans only weeks, so many ships there have little own history.",
    "Thresholds rest on few real cases; they are starting values, not calibrated rates.",
    "Unexplained is not a claim of intent: it means the evidence available to this run does not account for "
    "the deviation.",
]
LIMIT_SPEED_ONLY = "Unusual is measured on speed; this event type is assessed by the ship's speed only."
# Which sources can explain which measure (alibi.unusual.measure_for). Behaviour sources outside the
# set answer neutral with a fixed sentence; position_quality counts as an explainer for gaps only
# (patchy reception explains a silence, it never explains a speed change).
SPEED_SOURCES = {"sea_state", "ice", "own_habit", "place", "fleet", "notices"}
APPLIES = {"speed": SPEED_SOURCES, "grounding": SPEED_SOURCES,
           "gap": {"fleet", "position_quality"},
           "loiter": {"sea_state", "ice", "place", "fleet", "notices"}}
NOT_APPLICABLE = {
    "gap": "This source speaks to speed, not to a gap in AIS reports.",
    "loiter": "This source speaks to passing speed, not to lingering in one place.",
    "speed": "This source does not bear on this event.", "grounding": "This source does not bear on this event.",
}
LIMIT_TRACK_MODE = "The event was found by ALIBI's reference detector over the submitted track, not by the caller."
LAMP_ORDER = ["explains", "not_explained", "neutral", "unavailable"]
STATUS_LAMP = {"supports_explanation": "explains", "weakens_explanation": "not_explained", "neutral": "neutral",
               "unavailable": "unavailable"}
BEHAVIOUR = {s["id"] for s in config.SOURCES if s["kind"] == "behaviour" and s["id"] != "profile"}
TITLES = {s["id"]: s["title"] for s in config.SOURCES}

# ITU ship type codes and DMA type names -> our type groups (alibi_lab.profile_db)
ITU_GROUPS = {3: "fishing/tug/special", 4: "high speed", 5: "service", 6: "passenger", 7: "cargo", 8: "tanker", 9: "other"}
NAME_GROUPS = {"cargo": "cargo", "tanker": "tanker", "passenger": "passenger", "hsc": "high speed", "high speed": "high speed",
               "tug": "tug", "towing": "tug", "fishing": "fishing", "pleasure": "pleasure", "sailing": "pleasure",
               "pilot": "service", "sar": "service", "port tender": "service", "law enforcement": "service",
               "dredging": "service", "military": "other", "other": "other"}


def _epoch(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def track_frame(req: AssessmentRequest) -> pd.DataFrame:
    rows = [(_epoch(o.timestamp), o.latitude, o.longitude, o.sog_knots, o.cog_degrees, o.heading_degrees,
             o.pos_acc, o.raim) for o in req.track]
    df = pd.DataFrame(rows, columns=["time", "lat", "lon", "sog", "cog", "heading", "pos_acc", "raim"])
    for c in ("sog", "cog", "heading", "pos_acc", "raim"):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
    return df.sort_values("time", kind="stable").drop_duplicates("time", keep="last").reset_index(drop=True)


# -- vessel ---------------------------------------------------------------------------------

def _group(ship_type, cls_hint: str | None) -> str:
    if ship_type is not None:
        s = str(ship_type).strip().lower()
        if s.isdigit():
            t = int(s)
            return {30: "fishing", 31: "tug", 32: "tug", 52: "tug", 36: "pleasure", 37: "pleasure"}.get(
                t, ITU_GROUPS.get(t // 10, "unknown"))
        for k, g in NAME_GROUPS.items():
            if s.startswith(k):
                return g
    return cls_hint.rsplit("/", 1)[0] if cls_hint else "unknown"


def resolve_vessel(pdata: profiles.ProfileData, req: AssessmentRequest) -> dict:
    meta = req.metadata or {}
    mmsi = imo = None
    if req.event and req.event.vessel_id:
        vid = "".join(ch for ch in req.event.vessel_id if ch.isdigit())
        if vid:
            if req.event.identifier_type == "IMO" or (req.event.identifier_type is None and len(vid) == 7):
                imo = int(vid)
            elif req.event.identifier_type in (None, "MMSI"):
                mmsi = int(vid)
    for k in ("mmsi",):
        if mmsi is None and str(meta.get(k) or "").isdigit():
            mmsi = int(meta[k])
    if imo is None and str(meta.get("imo") or "").replace("IMO", "").strip().isdigit():
        imo = int(str(meta["imo"]).replace("IMO", "").strip())
    known = pdata.keys.get(mmsi) if mmsi is not None else None
    key = known["vessel_key"] if known else (pdata.imo_key.get(imo) if imo else None)
    if key is None and imo:
        key = f"IMO{imo}"
    if key is None and mmsi is not None:
        key = f"MMSI{mmsi}"
    vp = pdata.vessels.get(key) if key else None
    if imo is None and known and known["imo"] == known["imo"] and known["imo"] is not None:
        imo = int(known["imo"])
    length = meta.get("length_m") or (known or {}).get("length")
    length = float(length) if length is not None and length == length else None
    cls = (known or {}).get("cls") or (vp or {}).get("cls")
    group = (known or {}).get("group") if known else None
    if not cls or cls.startswith("unknown"):
        group = _group(meta.get("ship_type"), cls)
        size = "?"
        for lo, hi, label in [(0, 50, "S"), (50, 120, "M"), (120, 200, "L"), (200, 1e9, "XL")]:
            if length is not None and lo <= length < hi:
                size = label
        cls = f"{group}/{size}"
    group = group or cls.rsplit("/", 1)[0]
    mmsis = sorted(set(pdata.key_mmsis.get(key, [])) | ({mmsi} if mmsi is not None else set()))
    name = meta.get("vessel_name") or (known or {}).get("name") or (vp or {}).get("name")
    return {"vessel_key": key, "mmsi": mmsi, "imo": imo, "name": name, "cls": cls, "group": group,
            "length": length, "mmsis": mmsis}


# -- reference detector (track mode) ------------------------------------------------------------

def builtin_detect(track: pd.DataFrame, sensitivity: float) -> list[dict]:
    """The lab-03 rule pair over 10-minute windows (5 at high sensitivity), as a fallback when the
    shared `rules` package is not there: a window is too slow below 0.7 x the journey so far, or
    (sensitivity >= 0.5) more than 4 sigma and 10 % below it. Flagged windows are not learnt."""
    win = 300 if sensitivity >= 0.9 else 600
    t0 = int(track["time"].iloc[0])
    learnt: list[float] = []
    flagged: list[tuple[int, int, float, float]] = []
    for w, g in track.dropna(subset=["sog"]).groupby((track["time"] - t0) // win):
        if len(g) < 3:
            continue
        obs = float(g["sog"].median())
        ref = float(np.median(learnt)) if learnt else None
        hit = False
        if ref is not None and ref >= U.MOVING_KN:
            hit = obs < 0.7 * ref
            if not hit and sensitivity >= 0.5 and len(learnt) >= 3:
                m = np.asarray(learnt)
                scale = max(1.4826 * float(np.median(np.abs(m - np.median(m)))), U.SCALE_FLOOR_KN)
                hit = obs < ref - 4 * scale and obs < 0.9 * ref
        if hit:
            flagged.append((int(g["time"].iloc[0]), int(g["time"].iloc[-1]), obs, ref))
        elif obs >= U.MOVING_KN:
            learnt.append(obs)
    events, cur = [], None
    for a, b, obs, ref in flagged:
        if cur and a - cur["end"] <= win + 60:
            cur["end"], cur["obs"] = b, cur["obs"] + [obs]
        else:
            cur = {"start": a, "end": b, "obs": [obs], "ref": ref}
            events.append(cur)
    out = []
    for i, e in enumerate(events):
        sub = track[(track["time"] >= e["start"]) & (track["time"] <= e["end"])]
        out.append({"event_id": f"ref-{i + 1}", "event_type": "slowdown", "start_time": iso(e["start"]),
                    "end_time": iso(e["end"]), "location": {"latitude": float(sub["lat"].median()),
                                                            "longitude": float(sub["lon"].median())},
                    "baseline_summary": {"rule": "builtin_lab03", "observed_kn": round(float(np.median(e["obs"])), 2),
                                         "reference_kn": round(e["ref"], 2)}})
    return out


def detect(track: pd.DataFrame, sensitivity: float) -> tuple[list[dict], str]:
    try:
        import rules
        fn = getattr(rules, "detect", None)
    except Exception:  # noqa: BLE001
        fn = None
    if fn is not None:
        return list(fn(track[["time", "lat", "lon", "sog", "cog", "heading"]].copy(), sensitivity)), "rules"
    return builtin_detect(track, sensitivity), "builtin_lab03"


def _significance(ev: dict) -> float:
    b = ev.get("baseline_summary") or {}
    dur = (pd.Timestamp(ev["end_time"]) - pd.Timestamp(ev["start_time"])).total_seconds() / 60
    obs, ref = b.get("observed_kn"), b.get("reference_kn")
    drop = (ref - obs) / ref if obs is not None and ref else 0.5
    return max(drop, 0.05) * max(dur, 1.0)


# -- assessment -------------------------------------------------------------------------------

def _lamps(findings: list[Finding], enabled: set[str]) -> dict:
    out = {}
    for lamp in ("WX", "ICE", "PLC", "GNSS", "TRF"):
        states = [STATUS_LAMP.get(f.status, "neutral") for f in findings if f.lamp == lamp]
        if lamp == "GNSS":  # quality: problems found -> not_explained (confidence lowered)
            states = ["not_explained" if f.confidence_penalty > 0 and f.status != "unavailable" else
                      STATUS_LAMP.get(f.status, "neutral") for f in findings if f.lamp == lamp]
        out[lamp] = min(states, key=LAMP_ORDER.index) if states else "unavailable"
    return out


def _confidence(findings: list[Finding], disabled: list[str], tier: str, pre_minutes: float) -> dict:
    penalty, reasons = 0.0, []
    for f in findings:
        if f.confidence_penalty > 0:
            penalty += f.confidence_penalty
            if f.status == "unavailable":
                reasons.append(f"{TITLES.get(f.source_id, f.source_id)}: not available for this event.")
            else:
                reasons.append(f"{TITLES.get(f.source_id, f.source_id)}: {f.summary}")
    off = [s for s in disabled if s in BEHAVIOUR]
    if off:
        penalty += min(0.3, 0.1 * len(off))
        reasons.append(f"{len(off)} behaviour source(s) switched off for this run: {', '.join(off)}.")
    if tier == "prototype":
        penalty += 0.25
        reasons.append("No own history for this ship; it is compared with ships of its class.")
    elif tier == "journey":
        penalty += 0.1
        reasons.append("Little own history for this ship; its expected speed rests mostly on this journey.")
    if pre_minutes < 60:
        penalty += 0.2
        reasons.append("Less than an hour of track before the event.")
    level = "high" if penalty < 0.25 else "medium" if penalty < 0.55 else "low"
    if not reasons:
        reasons.append("All enabled sources were available and the ship has its own history.")
    return {"level": level, "reasons": reasons, "penalty": round(penalty, 3)}


def _signature(track: pd.DataFrame, ctx: Context, sigma: float, findings: list[Finding]) -> dict:
    t0, t1 = int(track["time"].iloc[0]) // 60 * 60, int(track["time"].iloc[-1])
    steps = np.arange(t0, t1 + 1, 60)
    tt, sog = track["time"].to_numpy(float), track["sog"].to_numpy(float)
    ok = np.isfinite(sog)
    tt, sog = tt[ok], sog[ok]
    obs = np.full(len(steps), np.nan)
    if len(tt):
        j = np.clip(np.searchsorted(tt, steps), 1, max(len(tt) - 1, 1))
        jl = np.clip(j - 1, 0, len(tt) - 1)
        jr = np.clip(j, 0, len(tt) - 1)
        pick = np.where(np.abs(tt[jl] - steps) <= np.abs(tt[jr] - steps), jl, jr)
        near = np.abs(tt[pick] - steps) <= 90
        obs[near] = sog[pick][near]
    exp = ctx.expected_kn
    band = max(2 * sigma, 0.1 * exp) if exp else None
    delta = np.zeros(len(steps))
    for f in findings:
        if f.expected_delta_kn and f.source_id in BEHAVIOUR:
            pts = sorted(f.expected_delta_kn)
            delta += np.interp(steps, [p[0] for p in pts], [p[1] for p in pts], left=0.0, right=0.0)
    adj = np.maximum(exp + delta, 0.0) if exp else None
    state = []
    for i in range(len(steps)):
        if exp is None or not np.isfinite(obs[i]):
            state.append(None)
        elif obs[i] >= exp - band:
            state.append(0)
        elif obs[i] >= adj[i] - band:
            state.append(1)
        else:
            state.append(2)
    r = lambda x: None if x is None or not np.isfinite(x) else round(float(x), 2)  # noqa: E731
    n = len(steps)
    return {"t": [iso(s) for s in steps], "observed_kn": [r(x) for x in obs],
            "expected_profile_kn": [r(exp)] * n if exp else [None] * n, "band_profile_kn": [r(band)] * n,
            "expected_adjusted_kn": [r(x) for x in adj] if exp else [None] * n, "band_adjusted_kn": [r(band)] * n,
            "state": state, "event_start": iso(ctx.event_start), "event_end": iso(ctx.event_end)}


def new_id() -> str:
    return f"asm_{int(time.time() * 1000):012x}{uuid.uuid4().hex[:12]}"


def assess(req: AssessmentRequest, options: AssessmentOptions | None = None) -> dict:
    opts = options or req.options or AssessmentOptions()
    pdata = profiles.get()
    reg = registry()
    enabled = list(config.SOURCE_IDS) if opts.enabled_sources is None else \
        ["profile"] + [s for s in dict.fromkeys(opts.enabled_sources) if s != "profile"]
    unknown = [s for s in enabled if s not in config.SOURCE_IDS]
    if unknown:
        raise BadRequest("unknown_source", f"Unknown source id(s): {', '.join(unknown)}.",
                         {"known": config.SOURCE_IDS})
    disabled = [s for s in config.SOURCE_IDS if s not in enabled]
    track = track_frame(req)
    if track["sog"].notna().sum() < config.MIN_TRACK_POINTS:
        raise Unassessable("track_too_short", f"The track needs at least {config.MIN_TRACK_POINTS} positions "
                           "with speed over ground.", {"points_with_sog": int(track["sog"].notna().sum())})
    vessel = resolve_vessel(pdata, req)

    details: dict = {}
    if req.event is not None:
        event = req.event.model_dump(mode="json", exclude_none=True)
        detected_by = "upstream"
        start, end = _epoch(req.event.start_time), _epoch(req.event.end_time)
        if end < start:
            raise BadRequest("invalid_event", "The event ends before it starts.")
    else:
        events, detector = detect(track, opts.sensitivity)
        detected_by = "reference_detector"
        details["detector"] = detector
        if events:
            events.sort(key=_significance, reverse=True)
            event, others = events[0], events[1:]
            details["other_events"] = others
        else:  # nothing found: assess the last hour, so a quiet track still gets an answer
            end = int(track["time"].iloc[-1])
            event = {"event_id": "track-review", "event_type": "track_review", "start_time": iso(end - 3600),
                     "end_time": iso(end)}
            details["note"] = "The reference detector found no candidate event; the last hour of the track was assessed."
        start, end = _epoch(pd.Timestamp(event["start_time"]).to_pydatetime()), \
            _epoch(pd.Timestamp(event["end_time"]).to_pydatetime())
    if vessel["mmsi"] is not None:
        event.setdefault("vessel_id", str(vessel["mmsi"]))
        event.setdefault("identifier_type", "MMSI")
    measure = U.measure_for(event.get("event_type"))
    ev = track[(track["time"] >= start) & (track["time"] <= end)]
    if measure == "gap":  # a gap has no positions inside; judge speed from the reports either side
        ev = track[(track["time"] >= start - 300) & (track["time"] <= end + 300)]
    if ev["sog"].notna().sum() < 1:
        raise Unassessable("no_track_in_event", "The track has no positions with speed inside the event window.",
                           {"event_start": iso(start), "event_end": iso(end)})
    pre = track[track["time"] < start]
    if "location" in event and event["location"]:
        lat, lon = float(event["location"]["latitude"]), float(event["location"]["longitude"])
    else:
        lat, lon = float(ev["lat"].median()), float(ev["lon"].median())
        event["location"] = {"latitude": round(lat, 5), "longitude": round(lon, 5)}

    ex = U.expected(pdata, vessel, pre)
    observed = float(ev["sog"].median())
    baseline = float(pre["sog"].median()) if pre["sog"].notna().any() else None
    tier = ex["tier"]
    cov = profiles.coverage(lat, lon, (start + end) // 2)
    summary = event.get("baseline_summary") or {}
    um = U.unusual(ex["expected_kn"], observed, ex["sigma_kn"]) if tier != "working" else {"unusual": None}
    if tier == "working":
        um = {"unusual": None, "measure": measure}
    elif measure == "gap":
        um = {**U.gap(track, start, end, summary), "speed": um}
    elif measure == "loiter":
        tile = pdata.tile(lat, lon, vessel["group"]) if cov and pdata.segments_ok else None
        um = {**U.loiter(ev, start, end, tile), "speed": um}
    elif measure == "grounding":
        um = {**U.grounding(track, start, summary, um.get("unusual")), "speed": um}
    else:
        um = {**um, "measure": "speed"}
    u = um["unusual"]
    cog = ev["cog"].dropna()
    ctx = Context(track=track, event_start=start, event_end=end, lat=lat, lon=lon,
                  vessel={**{k: v for k, v in vessel.items() if k != "mmsis"}, "profile_tier": tier},
                  expected_kn=ex["expected_kn"], observed_kn=observed, baseline_kn=baseline,
                  cog_deg=float(np.degrees(np.arctan2(np.sin(np.radians(cog)).mean(), np.cos(np.radians(cog)).mean())) % 360)
                  if len(cog) else None, unusual=u, sensitivity=opts.sensitivity,
                  extra={"profiles": pdata, "coverage": cov, "mmsis": vessel["mmsis"], "own_profile": ex.get("own"),
                         "class_speed": ex.get("class_speed_kn"), "sigma": ex["sigma_kn"], "metadata": req.metadata or {},
                         "measure": measure, "event_type": event.get("event_type"), "summary": summary})

    findings: list[Finding] = []
    for sid in config.SOURCE_IDS[1:]:
        if sid not in enabled:
            continue
        exp_ = reg[sid]
        if sid in BEHAVIOUR and sid not in APPLIES[measure]:
            findings.append(Finding(sid, "neutral", NOT_APPLICABLE[measure], lamp=getattr(exp_, "lamp", None),
                                    details={"measure": measure, "applies": False}))
            continue
        try:
            f = exp_.evaluate(ctx)
        except Exception as e:  # noqa: BLE001 - one failing source must not fail the assessment
            f = Finding(sid, "unavailable", "This source failed for this event.", 0.0, 0.1,
                        getattr(exp_, "lamp", None), details={"error": f"{type(e).__name__}: {e}"})
        if f.lamp is None:
            f.lamp = getattr(exp_, "lamp", None)
        kind = getattr(exp_, "kind", "behaviour")
        if kind == "identity":
            f.status, f.explains, f.expected_delta_kn = "identity_context_only", 0.0, None
        elif kind == "quality" and sid not in APPLIES[measure]:
            f.explains, f.expected_delta_kn = 0.0, None
        f.explains = float(min(1.0, max(0.0, f.explains or 0.0)))
        findings.append(f)

    x = None
    if u is not None:
        x = u
        for f in findings:
            if f.source_id in APPLIES[measure]:
                x *= 1 - f.explains
        x = round(min(x, u), 4)
    threshold = round(0.75 - 0.5 * opts.sensitivity, 4)
    if u is None:
        band, headline = "not_scored", HEADLINES["working" if tier == "working" else "unknown"]
    elif x >= threshold:
        band, headline = "top", HEADLINES["top"]
    else:
        band = "lower"
        headline = HEADLINES["usual"] if u < 0.3 else HEADLINES["most" if x < 0.5 * u else "part"]
    conf = _confidence(findings, disabled, tier, (start - int(track["time"].iloc[0])) / 60)
    limitations = [config.coverage_sentence(), *LIMITATIONS]
    if measure == "speed" and event.get("event_type") not in ("slowdown", "track_review"):
        limitations.append(LIMIT_SPEED_ONLY)
    if detected_by == "reference_detector":
        limitations.append(LIMIT_TRACK_MODE)
    details["unusual"] = {"expected_kn": _r(ex["expected_kn"]), "observed_kn": _r(observed), "baseline_kn": _r(baseline),
                          "sigma_kn": _r(ex["sigma_kn"]), "sigma_from": ex.get("sigma_from"),
                          "weights": ex.get("weights"), "components_kn": ex.get("components_kn"),
                          "history_tier": ex.get("history_tier"), "journey_hours": ex.get("journey_hours"), **um}
    details["coverage"] = cov
    details["confidence_penalty"] = conf.pop("penalty")

    out = {
        "assessment_id": new_id(), "api_version": API_VERSION,
        "assessed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z",
        "headline": headline, "event": event,
        "measures": {"unusual": u, "unexplained": x, "band": band, "top_threshold": threshold},
        "confidence": conf,
        "findings": [_finding_out(f, opts.include_evidence) for f in findings],
        "configuration": {"sensitivity": opts.sensitivity, "enabled_sources": enabled, "model_version": MODEL_VERSION,
                          "profile_version": config.PROFILE_VERSION, "api_version": API_VERSION,
                          "detected_by": detected_by},
        "limitations": limitations,
        "vessel": {"vessel_key": vessel["vessel_key"], "mmsi": vessel["mmsi"], "imo": vessel["imo"],
                   "name": vessel["name"], "cls": vessel["cls"], "profile_tier": tier},
        "lamps": _lamps(findings, set(enabled)),
        "signature": _signature(track, ctx, ex["sigma_kn"], findings) if opts.include_signature else None,
        "details": _clean(details),
    }
    return out


def _r(x, n: int = 2):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), n)


def _finding_out(f: Finding, include_evidence: bool) -> dict:
    return {"source_id": f.source_id, "status": f.status, "summary": f.summary,
            "explains": round(f.explains, 4) if f.status != "identity_context_only" else None,
            "lamp": f.lamp, "observed_at": f.observed_at, "source_reference": f.source_reference,
            "details": _clean(f.details) if include_evidence else None}


def _clean(v):
    """JSON-safe: numpy scalars to Python, NaN to None."""
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v
