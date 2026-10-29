"""The explainer contract: every source of evidence is a plug-in with the same shape.

An explainer gets the assessment context (the event, the track, the vessel and its expected
behaviour) and returns one Finding. Behaviour explainers say how much of the deviation they
account for (`explains`, 0..1). Quality explainers only move confidence. Identity explainers
are shown and never touch Unusual or Unexplained.

Unavailable data is its own status: it lowers confidence and never raises suspicion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

import pandas as pd

Status = Literal["supports_explanation", "weakens_explanation", "neutral", "unavailable", "identity_context_only"]
Kind = Literal["behaviour", "quality", "identity"]
Lamp = Literal["WX", "ICE", "PLC", "GNSS", "TRF"]


@dataclass
class Context:
    """Everything an explainer may look at. Built once per assessment by alibi.assess."""
    track: pd.DataFrame          # columns: time (epoch s UTC), lat, lon, sog, cog, heading, pos_acc, raim; sorted by time
    event_start: int             # epoch s UTC
    event_end: int               # epoch s UTC
    lat: float                   # event location (median of the event window if not given)
    lon: float
    vessel: dict                 # vessel_key, mmsi, imo, name, cls, group, length, profile_tier
    expected_kn: float | None    # ALIBI's expected speed for this ship before any explainer (the profile blend)
    observed_kn: float | None    # median SOG over the event window
    baseline_kn: float | None    # median SOG over the pre-event part of the track
    cog_deg: float | None        # median course over the event window
    unusual: float | None        # ALIBI's Unusual measure, 0..1
    sensitivity: float = 0.5
    extra: dict = field(default_factory=dict)  # caller metadata and anything explainers share

    @property
    def event_track(self) -> pd.DataFrame:
        t = self.track["time"]
        return self.track[(t >= self.event_start) & (t <= self.event_end)]

    @property
    def pre_track(self) -> pd.DataFrame:
        return self.track[self.track["time"] < self.event_start]


@dataclass
class Finding:
    source_id: str
    status: Status
    summary: str                 # one fixed, human-written sentence with numbers filled in
    explains: float = 0.0        # share of the deviation this source accounts for, 0..1 (behaviour only)
    confidence_penalty: float = 0.0  # 0..1, how much this finding lowers confidence (quality, unavailable data)
    lamp: Lamp | None = None
    observed_at: str | None = None   # ISO UTC of the data used
    source_reference: str | None = None  # product / dataset / file id, for the audit trail
    details: dict = field(default_factory=dict)
    # Optional per-step adjustment of the expected speed for the signature trace: list of (epoch s, delta kn).
    # Negative = the explainer expects the ship to be slower than its profile at that time.
    expected_delta_kn: list[tuple[int, float]] | None = None


class Explainer(Protocol):
    id: str
    title: str
    kind: Kind
    attribution: str

    def evaluate(self, ctx: Context) -> Finding: ...
