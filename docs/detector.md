# The demo detector and its rules

The detector is a stand-in for "your existing AIS system": stateless rules over one ship's track, deliberately
sensitive. ALIBI is the second opinion that makes that sensitivity affordable. The rules live in `rules/` (shared:
ALIBI's track mode imports the same package); the tool around them is `detector/`.

## Commands

```
python -m detector cases [--only id,id] [--no-counts] [--out DIR]   # build data/cases/*.json, index.json, detector_counts.csv
python -m detector replay --case eagle_s_2024 --api http://127.0.0.1:8601/api/v1 [--sensitivity 0.5] [--sources a,b]
python -m detector serve                                            # detector/web + /cases/ on 127.0.0.1:8600
python -m detector live --ais-dir <recorder ais dir> [--every 600] [--once]   # data/cases/live_gof.json
```

`replay` talks to ALIBI over HTTP only (httpx; `POST /assessments/batch` if it exists, else one call per candidate)
and writes `data/results/<case>__<config>.json`. `cases --out DIR` writes a committed snapshot: third-party cases
(Eagle S, Danish archive cases) are skipped and every file is kept under 14 MB. `live` re-reads the last 6 h of our
recording (including the open hour) every 10 min and replaces `live_gof.json` atomically; Gulf of Finland only, since
Denmark has no open live feed.

## Sensitivity

`rules.tier(s)`: s < 0.4 is tier 0 (conservative), s < 0.8 is tier 1 (default 0.5), otherwise tier 2. A case file holds
the candidates of the most sensitive tier, each with `baseline_summary.min_tier` (also `metadata.min_tier` and
`min_sensitivity`): the lowest tier at which the same rule also fires. Replay filters on it, so "detector alone" and
"detector + ALIBI" always see exactly the same events.

## The rules

| Rule | Event type | What it looks at |
|---|---|---|
| Slowdown | `slowdown` | 10-min median speed against the ship's own previous hour. Only for ships cruising at 6 kn or more, steady for 30 min or more. |
| Eagle S fingerprint | `slowdown` + `fingerprint="steady_cruise_drop"` | Annotation: over an hour of very steady cruise, then a sustained 15-35 % drop with the course held. |
| Grounding pattern | `grounding_pattern` | Straight run at 6 kn or more, speed below 1 kn within 6 min, and it stays there. Template: TERRY, Oresund, 22 Mar 2012. |
| AIS gap | `ais_gap` | A moving ship in good coverage not heard for more than 15 min. |
| Corridor loiter | `corridor_loiter` | Slow (under 4 kn) or curling about for 20 min or more inside a cable or pipeline corridor buffer. |

**Slowdown.** Rule A: window median below 0.7 x the reference. Rule B (tier 1 and up): below the reference minus
4 sigma and below 0.9 x the reference, with sigma the spread of the ship's own window medians (at least 0.3 kn). This is
the lab 03 pair. Tier 2 uses 5-minute windows. The reference is frozen when a change starts, so a lasting slowdown cannot
teach itself to look normal; changes are tracked with the most sensitive rule for every tier and the tier only decides
which are reported. An event ends when the speed is back for 3 minutes, when the ship stops, or after 3 h (after that it
is the ship's new normal). On our Eagle S replay the rules flag it 58.9 min (tier 0), 7.9 min (tier 1) and 5.9 min (tier 2)
after the speed starts to fall (10:13:04 UTC).

**Arrivals.** Every berthing and anchoring looks like a slowdown. An event that ends with the ship stopped is marked
`ends_stopped`; tier 0 drops those reaching the stop within an hour of onset, tier 1 drops those stopping in a *learnt stop
area* (grid cells of about 2 km where three or more ships each sat still for 20 min or more, learnt from the same window's
traffic by `rules.learn_stop_areas`), tier 2 keeps them. The same stop-area test applies to the grounding and corridor
rules at tiers 0-1. Without the layer (`stops=None`) nothing is excluded.

**Grounding.** Needs a straight run (course spread under 12 degrees for 10 min, 8 kn or more at tier 0, 6 kn otherwise),
then speed under 1 kn within 6 min (5 at tier 0), then at least 80 % of the next 20 min under 1 kn within 0.6 km. Tier 0
also needs erratic turning in the preceding hour. It rests on one confirmed case; it will fire on ferries berthing at speed
and on crash stops. That is intended.

**AIS gap.** Guards: moving before (median of the last 5 reports at least 2 kn), well covered (heard at least every 3 min
before and after), and not our own outage. A track that merely ends is not a gap. Tier 0 wants 30 min. Over a day in the
Gulf of Finland the rule fires rarely because Digitraffic coverage is dense; in the Danish archive, coverage edges would
produce many, which is why those cases rank gaps low.

**Recorder gaps are excluded.** A dead recorder is not a dark ship. The replay passes the recorder's own outages to the gap
rule: every disconnect/stop to the next resume in `data/ais/gaps-*.jsonl` (and the reported silences), plus fleet-wide silences in
the data itself (3 min or more at under 10 % of the usual message rate), each padded by one to two minutes. The Danish archive
has no such ledger, so Danish cases carry no exclusion.

**Corridor loiter.** Corridors come from `rules/corridors.geojson`: hand-made, straight or coarsely bent segments between
published landing points (Wikipedia and operator pages) for Estlink 1 and 2, the Balticconnector gas pipeline and its parallel
telecom cable, C-Lion1 (Gulf of Finland part) and the Helsinki-Tallinn telecom cables. Each has an `uncertainty_km`
(3-4 km) used as the buffer half-width and a source note. **They are approximate and schematic**, not a cable register and not
for navigation. One honest caveat: the middle vertex of Estlink 2 was placed at the crossing position published in the Eagle S
technical report, so the Eagle S case is not an independent test of the corridor geometry. The 5 km around each line end are
ignored (harbour approaches).

## Event ids and vocabulary

`event_id` is `ev-` plus the first 12 hex digits of sha1(`mmsi|start|type`): the same track always gives the same ids. Event
types are `slowdown`, `grounding_pattern`, `ais_gap`, `corridor_loiter`. Nothing in the rules or their text says more than
the track shows; the AIS navigation status is never used.

## Honest notes

- It over-flags on purpose. On our recording the detector alone raises roughly 50-100 candidates a day at s=0, 150-230 at
  s=0.5 and 250-350 at s=1 for about 500 merchant ships (`data/cases/detector_counts.csv`). Most are ordinary: approaches,
  ferry manoeuvres, a ship choosing a new speed. That is the problem ALIBI is built to solve.
- Thresholds rest on one real slowdown case (Eagle S) and one grounding case (TERRY). The trade-off curve is the result, not one number.
- Fleet cases use merchant ships over 50 m only (cargo, tanker, passenger); working vessels are not scored by ALIBI.
- Danish cases are capped to the 60 most significant candidates (drop x duration; events the conservative tiers also fire on rank first);
  the Gulf of Finland fleet case keeps all.
- Third-party data: the Eagle S and Danish case files stay under `data/` and are never committed.
