# Prior work (before the hackathon, Oct 29-31 2026)

Alibi enters the Copernicus Marine Service Hackathon 2026 with the pieces below, built
2026-10-04..05. Everything else is built during the hackathon.

## Built before

| What | Where | Why it had to exist before |
|---|---|---|
| AIS recorder (Digitraffic MQTT -> hourly JSONL, gap ledger, verify) | `alibi_recorder/` | The feed is live only: a baseline must be recorded in advance. Recording since 2026-10-04 19:45 UTC (first hour on the PC), on Umbrel since 20:40 UTC. |
| Context recorder (hourly snapshots of navigational warnings, winter navigation, port calls, aids-to-navigation faults, restriction areas, fairways) | `alibi_recorder/context.py` | Also live-only: warnings, ice assistance and faults in force are not archived by their publishers. Started 2026-10-19. |
| Backup pull (Umbrel -> PC, checksum-verified) | `alibi_recorder/pull.py`, `tools/pull_task.py` | Safekeeping of the recording. |
| Ship profile research: loader, tracks, tiles, prototype/own/journey profiles, journey tracker | `alibi_lab/` | "Previous research": the profile method. |
| Lab notebooks 01-03 (first day, prototypes, Eagle S) | `lab/*.py` | Findings that shaped the method. |
| Profiles from existing AIS data: the Danish Maritime Authority archive (2024-10 → 2026-10) and our recording | `alibi_lab/dma.py`, `alibi_lab/profile_db.py`, `tools/dma_ingest.py`, `tools/profile_db_task.py` | History for profiles; our own recording is only weeks long. |
| Incident cut-outs from the Danish archive (groundings, candidates from press reports) | `alibi_lab/incidents.py`, `alibi_lab/remote_zip.py`, `tools/fetch_incidents.py` | Real cases to evaluate against. |
| Fleet-slowdown candidate lists (AIS only, no weather) | `data/derived/fleet_slowdown_candidates_*.csv` | Where to look for Copernicus cases. |
| Design brief, plan, API contract, recorder spec | `ALIBI-design-brief.md`, `alibi-plan.md`, `alibi-openapi.yaml`, `archive/` | The idea and the slices. Plan written 2026-10-04, rewritten 2026-10-25; brief and contract 2026-10-23. |

## Built during the hackathon

Copernicus Marine connection (wind, waves, currents), the "does the sea explain it" score,
everything user-facing. Nothing Copernicus-related was fetched or coded before the event.

## Data - never committed

`data/` is git-ignored in full:

- `data/ais/` - our recording of the Fintraffic Digitraffic marine AIS feed
  (digitraffic.fi; open data, license per digitraffic.fi terms - check and cite in the submission).
- `data/derived/` - parquet caches and profile JSON, regenerable from `data/ais/`.
- `data/external/eagle_s/` - Eagle S voyage AIS CSV and technical report from
  eagles-report.com (third party; used for evaluation only, not redistributed).
- `data/external/sanctions/` - EU designated vessels (Council Regulation 833/2014), CSV
  published by the Danish Maritime Authority (dma.dk), list of 24.07.2026, 734 vessels by IMO.
- `data/external/sanctions/opensanctions_ua_war_sanctions_entities.ftm.json` - Ukrainian
  military intelligence (GUR) "War & Sanctions" listings as compiled by OpenSanctions
  (dataset `ua_war_sanctions`, version 20261018), 1,487 vessels. An assessment by one party to
  the war, not a sanction; licence per opensanctions.org/licensing (non-commercial use).
- `F:/alibi-data/dma/` (outside the project) - Danish Maritime Authority AIS archive
  (aisdata.ais.dk), compacted to one position per ship per minute; raw zips deleted after
  compaction. `data/derived/profile_db/` holds the segments and profiles built from it and
  from our recording.

## Related work

**AIS Guardian** (Jaime Lopez, github.com/jaimelopez89/AISGuardian, lopez.fi/aisguardian; MIT).
A real-time Baltic monitor built on Kafka and Flink: 12 rule-based detectors with fixed
thresholds, per its README - e.g. vessels below 2 kn in cable protection zones, AIS gaps
over 30 min, flags of convenience, exact IMO/MMSI match against ~130 sanctioned vessels,
rendezvous and convoy patterns, a cumulative risk score.

How Alibi differs:
- **Learned normal, not fixed thresholds.** Each ship is judged against its own history,
  its class and the area (our recording plus a year of the Danish archive), and its own
  journey so far. Eagle S crossed Estlink 2 under way at about 9 kn: a "below 2 kn in a
  cable zone" rule does not describe that; Alibi's journey tracker flagged the slowdown
  7 minutes after it began (lab 03).
- **The sea as an explanation.** Copernicus Marine wind, waves and currents (built during
  the hackathon) decide whether the sea explains what a ship does: a graded score with the
  evidence behind it, not a severity label per rule.
- **Measured, not asserted.** False-alarm rates per 10-minute window and detection of
  synthetic and real slowdowns are measured on held-out data (labs 02-03).
- **No live alerts.** Alibi ranks ships by how little their behaviour is explained and
  never names an act ("anchor dragging", "sabotage"). Single-signal alert rules fire on
  ordinary data: in one week of our recording 134 ships reported "at anchor" while moving at
  3 kn or more (a stale status field), while Eagle S broadcast "under way using engine"
  throughout its real anchor drag.
- **Sanctions as evidence, by IMO.** The official EU list (734 vessels) matched on IMO
  number: in two weeks 74 designated vessels were seen in the Gulf of Finland, many under
  names other than the listed one. Designation raises a ship's risk score; it is not by
  itself an alarm about behaviour.

Executed notebooks (`lab/*.ipynb`) and the generated Umbrel stack (`umbrel/compose.yaml`)
are outputs and are git-ignored too; they regenerate from the sources.
