"""Wire format: pydantic models mirroring `alibi-openapi.yaml` (the published contract).

The YAML is the contract; these models exist so FastAPI validates requests the same way
and documents responses in Swagger. Request models ignore unknown fields (clients may send
more than we read); response models are what we emit.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import config

LampState = Literal["explains", "not_explained", "neutral", "unavailable"]
FindingStatus = Literal["supports_explanation", "weakens_explanation", "neutral", "unavailable",
                        "identity_context_only"]


class _In(BaseModel):
    model_config = ConfigDict(extra="ignore")


class GeoPoint(_In):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class CandidateEvent(_In):
    model_config = ConfigDict(extra="allow")
    event_id: str
    event_type: str = Field(description="For example slowdown, loitering, or route_deviation.")
    vessel_id: str | None = None
    identifier_type: Literal["MMSI", "IMO", "other"] | None = None
    start_time: datetime
    end_time: datetime
    location: GeoPoint | None = None
    baseline_summary: dict[str, Any] | None = None


class AisObservation(_In):
    timestamp: datetime
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    sog_knots: float | None = Field(default=None, ge=0)
    cog_degrees: float | None = Field(default=None, ge=0, le=360)
    heading_degrees: float | None = Field(default=None, ge=0, le=360)
    nav_status: str | int | None = None
    pos_acc: bool | None = None
    raim: bool | None = None
    source: str | None = None


class AssessmentOptions(_In):
    sensitivity: float = Field(default=config.DEFAULT_SENSITIVITY, ge=0, le=1)
    enabled_sources: list[str] | None = Field(default=None, description="Source ids to run; default all. "
                                              "`profile` is always on.")
    include_evidence: bool = True
    include_signature: bool = True


class AssessmentRequest(_In):
    event: CandidateEvent | None = None
    track: list[AisObservation] = Field(min_length=2, max_length=50000)
    metadata: dict[str, Any] | None = None
    options: AssessmentOptions | None = None


class BatchRequest(_In):
    requests: list[AssessmentRequest] = Field(min_length=1, max_length=600)
    options: AssessmentOptions | None = Field(default=None, description="Overrides the options of every request "
                                              "(only the fields given here).")
    persist: bool = Field(default=False, description="Record each result in the ledger.")


# -- responses ---------------------------------------------------------------------------

class Measures(BaseModel):
    unusual: float | None = Field(description="Deviation from expected behaviour, 0..1; not a threat score. "
                                  "Null for working vessels (not scored).")
    unexplained: float | None = Field(description="Unusual x product of (1 - explained share) over enabled "
                                      "behaviour sources. Always <= unusual.")
    band: Literal["top", "lower", "not_scored"]
    top_threshold: float = Field(description="Unexplained at or above this is in the top band: 0.75 - 0.5 x sensitivity.")


class Confidence(BaseModel):
    level: Literal["low", "medium", "high"]
    reasons: list[str]


class FindingOut(BaseModel):
    source_id: str
    status: FindingStatus
    summary: str
    explains: float | None = None
    lamp: Literal["WX", "ICE", "PLC", "GNSS", "TRF"] | None = None
    observed_at: str | None = None
    source_reference: str | None = None
    details: dict[str, Any] | None = None


class Configuration(BaseModel):
    sensitivity: float
    enabled_sources: list[str]
    model_version: str
    profile_version: str
    api_version: str
    detected_by: Literal["upstream", "reference_detector"]


class Vessel(BaseModel):
    vessel_key: str | None = None
    mmsi: int | None = None
    imo: int | None = None
    name: str | None = None
    cls: str | None = None
    profile_tier: Literal["own", "prototype", "journey", "working"]


class Lamps(BaseModel):
    WX: LampState
    ICE: LampState
    PLC: LampState
    GNSS: LampState
    TRF: LampState


class Signature(BaseModel):
    t: list[str]
    observed_kn: list[float | None]
    expected_profile_kn: list[float | None]
    band_profile_kn: list[float | None]
    expected_adjusted_kn: list[float | None]
    band_adjusted_kn: list[float | None]
    state: list[int | None] = Field(description="0 inside the profile band, 1 outside it but inside the adjusted "
                                    "band (unusual, explained), 2 outside the adjusted band (unexplained).")
    event_start: str
    event_end: str


class Assessment(BaseModel):
    assessment_id: str
    api_version: str
    assessed_at: str
    headline: str
    event: dict[str, Any]
    measures: Measures
    confidence: Confidence
    findings: list[FindingOut]
    configuration: Configuration
    limitations: list[str]
    audit_reference: str | None = None
    vessel: Vessel | None = None
    lamps: Lamps | None = None
    signature: Signature | None = None
    details: dict[str, Any] | None = None


class Error(BaseModel):
    error: str
    message: str
    details: dict[str, Any] | None = None


class BatchError(Error):
    index: int


class Source(BaseModel):
    id: str
    title: str
    kind: Literal["behaviour", "quality", "identity"]
    lamp: str | None = None
    attribution: str
    available: bool = True


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    api_version: str
    model_version: str
    profile_version: str
    dependencies: dict[str, Literal["ok", "degraded", "unavailable", "not_checked"]]
