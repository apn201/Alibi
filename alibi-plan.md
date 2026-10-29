# ALIBI - Copernicus Marine Service Hackathon 2026, plan

ALIBI (Automatic Lookout for Irregular Baltic Itineraries). Solo entry, challenge: Enhancing Maritime Security and Resilience.

Written 2026-10-04, rewritten 2026-10-25 for the event. The governing product description is [ALIBI-design-brief.md](ALIBI-design-brief.md) (2026-10-23). This plan says how the brief gets built in two days. The earlier plan is in `archive/alibi-plan-2026-10-19.md`.

Related files: `README.md` (recorder as built), `PRIOR_WORK.md` (what existed before the event), `alibi-openapi.yaml` (API contract), `lab/` (findings).

## The idea in one paragraph

Monitoring tools that catch the next Eagle S have to be sensitive, and sensitive rules fire on ordinary ships all day. Operators stop looking. ALIBI is the second opinion: it takes what a detector flagged and tests whether the sea, the place, the ship's own habits or the traffic around it explain it. What is left is a short list worth a human's time. The sea is the alibi.

## Two parts, one story

| | AIS anomaly detector | ALIBI |
|---|---|---|
| Role | Raises suspicion. Cheap, fast, deliberately sensitive. | Tests explanations. Lowers suspicion where evidence allows. |
| In the real world | Any existing AIS / maritime-domain-awareness system. | Middleware those systems call. The product. |
| In the demo | A small stand-in we build, labelled demo. Owns the AIS feed, replay, the GUI. | A separate service with its own API. Runs without the GUI. |
| State | Stateless rules over a track window. | Profiles, place, environment, context, ship history. |
| Output | Candidate events: "slowdown, 10:13-10:43, here". | Assessment: Unusual, Unexplained, confidence, findings per source. |

This is the security-operations pattern: detection rules fire, the triage layer enriches and ranks, a person decides. It is the pattern from the security background the pitch already mentions, and it is why the split is not a demo trick.

### What the detector does

It really detects. It does not need learned profiles, because upstream systems in the real world mostly do not have them. Rules, all computed from the track alone:

- Slowdown against the ship's own journey: below 0.7 x, or 4 sigma of journey steadiness and at least 10 % (the lab 03 rule pair).
- Known fingerprints, written as rules:
  - Eagle S: long steady cruise, then a sustained drop of 20-30 % with course held. Lab 03: flagged at +7 min with the sensitive rule.
  - Grounding: erratic turning, then a straight run, then speed to zero within minutes outside an anchorage. TERRY 2012 is the confirmed template. The other Danish cases are candidates to check.
- AIS gap inside the receivers' heard area.
- Loitering or slow passage in a cable corridor (corridor layer with stated uncertainty).

The sensitivity knob lives here, and the detector is expected to over-flag. That is the point: lab 03 measured the price of catching Eagle S early as about 9 % of open-water 10-minute windows flagged, against 2 % for the conservative rule. ALIBI's job is to make that sensitivity affordable.

### What ALIBI does

ALIBI computes its own Unusual measure (second opinion, against own profile, prototype and journey) and then Unexplained, by running every enabled explainer. Each explainer is a plug-in with the same contract: given the event and track, return supports / weakens / neutral / unavailable, with its evidence and source.

ALIBI is not a weather tool. Weather is the explainer the hackathon is about. The list:

| Explainer | Source | Event build |
|---|---|---|
| Sea state: wind, waves, current, speed through water | Copernicus Marine | yes, the core |
| Ice | Copernicus sea ice + Digitraffic winter navigation | if time, Feb 2026 case |
| Own habit: "this ship always slows here" | profile DB | yes, exists |
| Place: anchorage, port approach, pilot area, tile normal | tiles, restriction areas, fairways | yes, partly exists |
| Fleet: the whole area slowed together | AIS, all ships nearby | yes, exists as the candidate finder |
| Notices: navigational warning, port call, restriction | context recorder | yes, data exists |
| Position quality | `posAcc`, `raim` | reduces confidence, never raises suspicion |
| Identity context: EU designation, GUR listing | sanctions files | shown, never changes Unexplained |

Fleet and sea state work together: the fleet explainer says "something slowed everybody", Copernicus says what. A fleet slowdown in calm sea stays unexplained (2-4 Jul 2026 is the counter-example to look at).

### What if the upstream system flags nothing?

A dumb AIS system never calls ALIBI, so ALIBI has to work without a detector too. The API gets two entry modes:

- Event mode: `POST /assessments` with an event and its track. The integration story.
- Track mode: the same call with a track and no event. ALIBI runs its own reference detector (the same rules as the demo detector, shipped as a library) and assesses what it finds.

So the detector logic exists twice by design: once in the demo GUI as "your AIS system", once inside ALIBI as the fallback. Same code, one package. The story holds whichever kind of customer integrates it. A batch or feed mode (ALIBI subscribes to a whole AIS feed) is the product's next step, not the event's.

### Where the line moves if time runs out

The demo may cut corners. The boundary may not: the detector GUI only talks to ALIBI over HTTP, and one saved event is POSTed with curl in the pitch. If the GUI is late, the demo is the API plus Swagger plus pre-rendered before/after numbers, which still tells the whole story.

## Profiles: how they stay fresh

Three speeds, matching the three profile tiers:

| Tier | Updated | How |
|---|---|---|
| This journey | continuously | In memory in the scorer, per ship, per message window. Already built (`JourneyTracker`). |
| Own profile, class prototype, place tiles | nightly | Batch job after midnight UTC on the previous day's closed hours. Writes a new versioned snapshot. |
| Model thresholds, prototype classes | by hand | Only after a re-test, never automatically. |

Nightly, not continuous, because:
- "Do not learn from what you flag" needs a decision per window. In a nightly run the day's assessments exist, so windows that stayed unexplained are left out of the learning set. A continuous learner would absorb a slow anomaly before anyone looked at it.
- Every assessment records the profile snapshot it used (`profile_version`). Reproducible, auditable, and a re-run of an old case gives the old answer.
- The data does not need faster: a frequent ship adds one or two journeys a day.

For the event the nightly job runs once, by hand, on Thursday, and the demo uses that snapshot. The job is shown, not scheduled.

## Data freeze for Thursday

The set the profiles are built from on Thursday:

| Source | Span | Where | State 2026-10-25 |
|---|---|---|---|
| Our Digitraffic recording | 2026-10-04 19:45 UTC → cut-off | `data/ais`, 2.0 GB, hourly pull | 503/504 hours have a file, 53 ledger events |
| Context recorder | 2026-10-19 → cut-off | `data/context`, 21 MB | running, 0 errors |
| Danish AIS archive, compacted | 2024-10-01 → 2026-10-17, 747 days | `F:\alibi-data\dma`, 19 GB | archive, used as it is; nothing more to add |
| Profile DB | dk 2024-10-01 → 2026-10-17, fi every complete day | `data/derived/profile_db` | rebuild running 2026-10-25 (task "Alibi profile DB rebuild (one-off)", log `build.log`) |
| Incident cut-outs | 9 cases | `data/external/dma_incidents` | fetched; only TERRY verified in the track |
| Eagle S | voyage AIS + report | `data/external/eagle_s` | evaluation only, never committed |
| Sanctions | EU 2026-07-24 (734 IMO), OpenSanctions GUR 2026-10-18 (1,487) | `data/external/sanctions` | |
| Demo-case candidates | fleet slowdowns fi + dk | `data/derived/fleet_slowdown_candidates_*.csv` | from AIS only |

The Danish data is an archive: used as it is, not extended. At the event it is described as existing AIS data the profiles were built from.

Before Thursday:
1. Rebuild the profile DB with both Danish years and every complete day of ours. Running since 2026-10-25.
2. Cut-off: our recording up to Wed 2026-10-28 23:59 UTC is "history". Everything after is "live" and never used to fit what it is tested on. Re-run `tools/profile_db_task.py` once after the cut-off; it only adds the missing days of ours (minutes).
3. Walk the incident list: confirm the fingerprint in the track or drop the case. A list of 3 verified beats 9 claimed.

On Thursday the repo gets the code and a profile snapshot built from the frozen set. Profiles are copied, not re-researched.

## Scaling: what a real deployment would cost

Calls only happen for flagged windows. Rough numbers:

- Our area: about 1,000 moving ships, six 10-minute windows an hour each, 9 % flagged by a sensitive detector: about 540 assessments an hour, one every 7 seconds.
- Global AIS, about 100,000 moving ships: about 15 a second. A few small stateless API workers behind a load balancer (Fargate, Lambda, or one VM) carry that.

Compute is not the cost. Upstream data is. Every assessment in the same sea area and hour asks the same question of Copernicus, so ALIBI never calls Copernicus per request:

- Environmental cache: the operating region's fields are fetched once per product update (hourly analysis and forecast), stored as tiles keyed by product, variable, hour and area (S3 or local disk, zarr or parquet). Assessments are lookups into it. A thousand calls about the Gulf of Finland at 10:00 cost one download.
- The same read-through cache fronts every slow source: nav warnings, port calls, ice. It is the proxy layer, and it is shared across all customers, which is where the economics are.
- Profile snapshots are read-only files, copied to every worker. The nightly job is the only writer.
- Assessment and evidence ledger: an append-only table (Postgres or DynamoDB). Small rows, a source reference instead of copied data.

For the event: a local cache filled before the demo for the demo cases and the last 48 hours, one process, SQLite ledger. The pitch shows the same diagram with the cloud names on it.

## Proof of value (unchanged from the brief)

Same cases, same baseline, same sensitivity:
1. Detector alone: how many candidates.
2. + ALIBI, AIS-only explainers.
3. + Copernicus.
4. + everything.
5. Sensitivity sweep: detection time for Eagle S against candidates per day.

Acceptance, measured not claimed:
- Replay every recorded day: the top band holds none or a stated handful, each explainable on inspection.
- Eagle S reaches the top band before Estlink 2 (+13 min), and Copernicus does not explain it away.
- At least one fleet slowdown where Copernicus moves the ships out of the top band, and one where it does not.

If the numbers do not support the hypothesis, the pitch says so.

## The model (from lab 02-03, still valid)

Predict what each ship should be doing; score the gap. Code: `alibi_lab/profiles.py`, `alibi_lab/profile_db.py`.

- Three profiles, blended: prototype per class (type group x length S/M/L/XL), own profile for frequent ships (primary when it exists), this journey (takes over within the hour for new ships, weighted low for frequent ones).
- Do not learn from what you flag. Report and learn are separate decisions.
- Features: speed, speed spread, crab angle, turn, 10-minute windows, median and spread, never the mean.
- Ships that do not cruise (tugs, pleasure craft, small ferries) need behaviour prototypes; until then they are greyed out as working vessels and not scored.
- Recorder gaps are excluded. A dead recorder is not a dark ship.
- What it claims: "slowed, and the sea does not explain it". It does not claim to see the anchor.

## Ship history

A per-ship evidence ledger keyed by IMO (a name or MMSI change is itself an entry). History makes ALIBI look harder; it never alarms on its own. Evidence decays by kind (behaviour about 60 days, AIS gap in a sensitive area about 90, identity change about a year, EU designation until lifted), clean passages and later explanations clear it, repeated patterns weigh more than their sum, and a higher score needs a different kind of evidence, not more of the same. Filled before use by replaying the history. For the event: the ledger table and the replay; the decay weights are stated as starting guesses.

## Copernicus demo cases

Found from AIS alone as fleet-wide slowdowns against each area's usual pace; no weather fetched before the event.
- Ours: 5-6 Oct 2026, 22:00-16:00 UTC, six areas 22-28 E, fleet at 65-83 % of usual. Ships unusual on their own are 2.3 x more common inside fleet slowdowns.
- Danish: 3-6 Oct 2025 (widest), 1-7 Feb 2026 (storm or ice), 31 Dec 2025 - 3 Jan 2026, 4-6 Apr 2026, 12-14 Mar 2026.
- Counter-example: 2-4 Jul 2026. If the sea was calm, it stays unexplained.
First thing at the event: check the Copernicus Baltic products cover the Danish straits and Kattegat, and that the past weeks are downloadable.

## The event

Online, Oct 29-31 2026, Ultrahack for Copernicus Marine Service. Time zone of the schedule to confirm (probably CET).
- Thu: 16:00 opening + checkpoint 1. 23:59 checkpoint 2 form.
- Fri: 09:00 checkpoint 2. 13:00 pitch training. 16:00 checkpoint 3 form. 17:00 checkpoint 3.
- Sat: 10:00 pitch materials due. 11:00 pitching. 15:00 awards.

Solo entry is allowed. Preparation is allowed as long as the repo does not exist before the event, so the repo is created Thursday after the opening.

Checkpoint 1 says plainly what existed before: our AIS recording, profiles built from existing AIS data, the profile research. Everything Copernicus and everything on screen is built in the window.

## Slices during the event

| # | Slice | When |
|---|---|---|
| H0 | Repo. Copy recorder, lab code, profile snapshot. Two packages: `detector/` and `alibi/`, shared `rules` library. | Thu, first hour after the 16:00 opening |
| H1 | Copernicus: fetch wind, waves, currents for the demo cases and recent days into the cache. Join to tracks, speed through water. | Thu evening |
| H2 | ALIBI service: `/health`, `POST /assessments`, `GET /assessments/{id}`, Swagger. Explainers: own habit, place, fleet, sea state. | Thu night - Fri morning |
| H3 | Detector: rules over replayed tracks, calls ALIBI. | Fri morning |
| H4 | GUI: signature board, ship sheet, source toggles, sensitivity. Look per the approved mockup. | Fri |
| H5 | Proof-of-value runs 1-5, numbers into a table. | Fri evening |
| H6 | Pitch, curl demo, limits slide. | Sat before 10:00 |

## Cut order

1. Ice explainer.
2. Ship-history component on screen (keep the ledger).
3. Live mode (replay is a complete demo).
4. Notices explainer.
5. GUI polish: fall back to Swagger + a static before/after page.

Never cut: the HTTP boundary between detector and ALIBI, the Copernicus join, the measured numbers, Unusual and Unexplained kept separate, identity context kept out of the score.

## Responsible use

- No live alerts. Ranked, least explained first. Even at the top: "behaving unusually, and the available evidence does not explain it".
- Fixed, human-written sentences only. No model-written text about a named ship.
- The AIS status field never triggers anything (134 ships a week report "at anchor" at 3 kn+; Eagle S said "under way" while dragging).
- EU designation and GUR listing shown as two separate kinds, each with source and date, by IMO. Neither explains or un-explains behaviour.
- Limits published with the tool: coverage, weeks of history, storms seen, no ice season in our own recording, few real cases behind the thresholds.
- Third-party case data (Eagle S): show results, not data.

## Open questions

- Hosting: helppox.com or apn201.com, decided when H2 runs.
- Wind product: Copernicus Marine wind first, FMI open data as fallback. Verify at H1.

## Risks

- Copernicus past fields not retrievable: no weather for the history, H1 has nothing to fit. Check in the first hour.
- Day 1 overload: H0 must be a copy job, which is why the data freeze and profile rebuild happen before Thursday.
- Thresholds rest on one real slowdown case and one grounding case. Report the trade-off curve, not one number.
