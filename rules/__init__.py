"""Detector rules, shared by the demo AIS tool (detector/) and ALIBI's track mode.

Stateless: every rule looks at one ship's track and nothing else, the way an ordinary
upstream AIS system would. Deliberately sensitive; ALIBI is what makes that affordable.

Contract (implemented in this package):

    detect(track: pandas.DataFrame, sensitivity: float = 0.5) -> list[dict]

`track` has columns time (epoch s UTC), lat, lon, sog, cog, heading (NaN where missing),
sorted by time, one ship. Returns CandidateEvent dicts as in alibi-openapi.yaml:
    {"event_id", "event_type", "start_time", "end_time" (ISO UTC, "Z"),
     "location": {"latitude", "longitude"}, "baseline_summary": {"rule", "observed_kn", "reference_kn", ...}}
event_type is one of: slowdown, grounding_pattern, ais_gap, corridor_loiter.
"""
