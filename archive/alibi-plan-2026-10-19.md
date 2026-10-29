# ALIBI - Copernicus Marine Service Hackathon 2026, plan

Written 2026-10-04, updated 2026-10-06. Solo entry.
Challenge: Enhancing Maritime Security and Resilience. One challenge only was the recommendation. Confirm what was ticked on the form.

Alibi watches the ships in the northern Baltic and asks one question of each: does the sea explain what you are doing. Most of the time it does. The map shows the ones where it does not.

It accuses nobody. A flagged ship may be in trouble, may be up to something, or may just be doing its business in an unusual way. Alibi says which ships are outside the pattern and what failed to explain it.

The name stays Alibi. "The sea is the alibi" is the pitch line.

Related files: `recorder-spec.md` (the recorder as specified), `README.md` (the recorder as built), `PRIOR_WORK.md` (what existed before the event), `lab/` (findings).

## Status on 2026-10-06

- Recording since 2026-10-04 19:45 UTC. First hour on the PC, on Umbrel since 20:40:20 UTC. One disconnect so far, 8.4 s of silence (Oct 5 02:55 UTC).
- Hourly backup pull from Umbrel to the PC runs and verifies checksums. The single-copy risk is closed.
- Registration is in. The summary shows on the submissions page.
- Lab 01-03 done on the first day of data: data quality, ship profiles, Eagle S replay.
- Nothing Copernicus-related has been fetched or coded. That is deliberate, see PRIOR_WORK.md.

## The event

- Online, Oct 29-31 2026. Organised via Ultrahack for Copernicus Marine Service.
- Selected teams announced Oct 15.
- Oct 22 14:00-15:30 CEST (15:00 Finnish): mentors and onboarding.
- Must use Copernicus Marine data. (Stated for past editions. Assumed here. Confirm.)
- Judged on: impact and challenge relevance, progress during the event, innovativeness, technical capability with a clear demo.
- Prize pool 3000 EUR split among top teams. Not the reason.

Hack days (time zone not stated on the page - confirm, probably CET, Finnish +1):
- Day 1 Thu: 16:00 opening + checkpoint 1. 23:59 checkpoint 2 form.
- Day 2 Fri: 09:00 checkpoint 2. 13:00 pitch training. 16:00 checkpoint 3 form. 17:00 checkpoint 3.
- Day 3 Sat: 10:00 pitch materials due. 11:00 pitching and Q&A. 15:00 awards.

Still open, one email to madde.kivikangas@ultrahack.org:
1. Is a solo entry accepted.
2. What preparation is allowed before the event. Our line is in PRIOR_WORK.md.

Other entries seen on Oct 5: three "risk intelligence" tools (what the sea does to ships), one retrospective satellite study, one GNSS interference locator (ORBITGUARD). Nobody else scores ship behaviour.

## What it shows

A map of the sea area Finnish AIS receivers hear: Gulf of Finland, Archipelago Sea, Gulf of Bothnia, northern Baltic proper. Not the whole Baltic. The report says so.

Per ship, two scores. They stay separate.

- Unusual - how far the ship is from its own past, from this journey so far, and from ships like it. This drives the heatmap.
- Unexplained - how much of the unusual part is left after weather, current, ice, traffic, place and position quality have had their say. This is the alibi.

It is a graded score, not a yes/no alarm. The operator picks the threshold. Lab 03 showed why: the sensitive rule that catches a real anchor drag early also costs false alarms.

Icons, none of which add heat:
- Sanctioned - EU designated vessels, matched by IMO number, source one click away.
- Listed by GUR - a separate icon for the Ukrainian military intelligence listing, with its reason and source. Not called "sanctioned".
- Working vessels - military, law enforcement, pilot, search and rescue, tug. They loiter and zigzag for a living, so they get an icon and no heat. AIS type codes 35, 55, 50, 51, 52 as recalled from the standard. Verify against the vessel snapshot before coding.

Each score comes with:
- the named factors that were checked and whether each one explained anything,
- a confidence level, set by which profile was available and how much data sits behind it.

Click a ship: its track, the speed it should have had, the speed it had, the factor list. Text on screen is fixed, human-written sentences. The model picks which sentence. It never writes one.

## Data

| Source | What | Use | Status |
|---|---|---|---|
| Digitraffic AIS (Fintraffic) | live positions and metadata, MQTT | the ships | recording, backed up hourly |
| Copernicus Baltic physics | currents, sea level, ice, 1 nm, hourly | speed through water, ice | during the event. Not checked that past weeks stay downloadable |
| Copernicus Baltic waves | wave height and direction | weather response | during the event. Same check |
| Wind | - | weather response | source not chosen. A Copernicus Marine wind product is the first candidate, FMI open data the fallback. Unverified |
| EMODnet Human Activities | cables, power cables, pipelines | infrastructure layer | not pulled. Check Gulf of Finland routes are real, not stylised |
| OpenSanctions maritime | sanctioned vessels by IMO | the icon | not pulled. Free for non-commercial use only |
| Eagle S voyage AIS and report (eagles-report.com) | one documented anchor drag, 25 Dec 2024 | evaluation only | in `data/external/`, third party, not redistributed |

Attribution lines for all of them go in the README and on the map. Map tiles: OpenStreetMap with Leaflet or MapLibre, not Google.

## What the first day of data said (lab 01, 2026-10-05, about 22 h)

- About 10 s between a vessel's reports. Minute-level detection is possible.
- Sentinels are rare except heading (13 % "511") and rate of turn.
- Ships' own tracks have gaps over 15 min (out of range, moored). Split tracks on gaps, never interpolate.
- The same ship repeats its route to within minutes and a few hundred metres. "Is this ship behaving like itself" is a sharper question than "like the tile".
- Tiles need the weeks. Grid 0.05 deg lat x 0.10 deg lon, about 5.5 km. About 110 tiles had 30+ passages on day one, about 1,550 of 2,500 expected by day 25.
- Filter by type before profiling. One tile had a 51 kn median.

## The model

Predict what each ship should be doing. Score the gap. Code: `alibi_lab/profiles.py`.

Three profiles, blended:
1. Prototype - a template per ship class (type group x length class S, M, L, XL). Every ship has one. Cold start for ships never seen.
2. Own profile - for ships seen again and again. Primary when it exists.
3. This journey so far - takes over within the hour for new ships. Weighted low for frequent ships.

Rules that came out of lab 02:
- Do not learn from what you flag. A baseline that follows the ship also follows its anomaly. The tracker stops learning a window in which the ship departs from its own journey.
- Report and learn are separate decisions. Flags compare with the whole blend.
- "Frequent" is measured in hours for now. Switch to repeat journeys on several days once there are a few days of data.
- Ships that do not cruise (tugs, pleasure craft, small ferries) need behaviour prototypes, not cruise speed. Until then they are noise. See working vessels above.

Features today: speed, speed spread, crab angle, turn. 10-minute windows. Use the middle value and the spread, never the average: a patch with a lane and an anchorage has two kinds of normal.

Two "too slow" rules, both kept, they are the two ends of the threshold:
- x0.7 - below 0.7 x expected.
- 4 sigma and x0.9 - 4 x the ship's own steadiness on this journey and at least 10 % slower.

Eagle S replay (lab 03, one real case, profiles from one day of our data):
- Speed is the whole signature: 12 kn steady for 6.5 h, then about 9 kn within 15 minutes. Crab angle shows nothing.
- x0.7 flags it about 67 minutes after the drag began, after every cable.
- The sensitive rule flags it about 7 minutes after, before Estlink 2 at +13 min, with no false flag in the 6.5 h before.
- Price in open water for cargo, tanker and passenger ships: about 2 % of windows flagged with x0.7 against about 9 % with the sensitive rule. Near stops both are noisy, about 20 %.
- Do not tune further on Eagle S alone.

Factors still to add, in this order:
1. Place - tiles, approaches, anchorages, pilot areas. Explains away the noise near stops.
2. Weather - Copernicus, during the event. Should remove open-water false alarms without explaining away Eagle S. That is the test.
3. Position quality - `posAcc` and `raim` from the position message. GNSS jamming and spoofing are reported in the Gulf of Finland, and a spoofed ship looks like the strangest vessel on the map. Not checked how reliably ships set these fields.
4. White space - "no ship of this type has been here in the recording". Per ship type. Only where other vessels have been heard, otherwise empty means unheard. Needs the confidence label more than any other factor. Mostly flags ships in trouble.
5. Pilot boarding - pilot boats identify themselves, so every boarding in the recording is a labelled event. Learn its signature and use it as a named explanation.
6. Status check - reported navigation status against behaviour.

Recorder gaps are excluded. A dead recorder is not a dark ship.

What it claims: "slowed and the sea does not explain it". It does not claim to see the anchor. AIS does not report the engine.

Out of scope: inferring an invisible vessel from another ship's behaviour. At most one fixed label, "looks like a boarding, no second vessel on AIS", and it is first on the cut list.

### Copernicus demo cases

Copernicus must be necessary, not decoration: ships that look suspicious on their own, whose score falls once the sea is taken into account. Found before the event from AIS alone, no weather data fetched: weather leaves a fingerprint when a whole fleet in a sea area slows down together, compared with its own usual pace there. Lists: `data/derived/fleet_slowdown_candidates_fi.csv` and `..._dk.csv` (2026-10-19).

- Our recording: 5-6 Oct 2026, 22:00-16:00 UTC, six areas 22-28 E across the Gulf of Finland, fleet at 65-83 % of usual. Ships unusual on their own are 2.3 x more common inside such fleet slowdowns.
- Danish archive (297 days): 3-6 Oct 2025 (13 areas at once, the widest), 1-7 Feb 2026 (127 h, storm or ice), 31 Dec 2025 - 3 Jan 2026, 4-6 Apr 2026, 12-14 Mar 2026, a winter series Dec-Jan.
- 2-4 Jul 2026 (8 areas, summer): keep as the counter-example. If Copernicus shows calm sea, it stays unexplained, and Alibi says so.

At the event: fetch wind, waves (and sea ice for February) for these times and places, re-score, show before and after. Check first that the Copernicus Baltic products cover the Danish straits and Kattegat.

### Ship history

A ship that acted oddly but triggered nothing, left, and came back. Its past should make Alibi look harder. It should not raise an alarm by itself.

1. Keep evidence, not scores. Every weak signal, also below the alarm threshold, goes into a per-ship ledger: what, when, where, how unusual, which model version. The score is computed from the ledger when asked. Weights can change later without losing facts, and every point of a score traces back to an event.
2. Key the ledger by IMO, so a new name or MMSI does not wipe the history. The change itself is a ledger entry.
3. History raises attention. A ship with unexplained weak signals gets a more sensitive detector on its next visit, for example 3 sigma instead of 4. On the risk map it shows as a separate history component: "nothing now; elevated because of 2 unexplained slowdowns over a cable corridor in September", with links to the events.
4. Old suspicion fades, each kind at its own pace. Starting guesses, to be calibrated:
   - weak behaviour signal (slowdown, loitering): half-life about 60 days
   - AIS gap in a sensitive area: about 90 days
   - identity change (name, flag, MMSI): about a year
   - EU designation: until lifted
5. A ship can clear itself. Every normal passage lowers the history component, for example by 20 %. An event that later gets an explanation (navigational warning, port call, storm in the Copernicus data) is marked explained and stops counting.
6. Patterns weigh more than their sum. Three weak slowdowns over cable corridors on different visits count for more than three scattered small deviations. Only a ledger across visits shows this.
7. No self-feeding loop. Closer watch produces more weak signals, which raise the score, which brings closer watch. So: history alone never alarms, evidence decays, and a higher score needs a different kind of evidence (behaviour and identity), not more of the same. False alarms are measured separately for ships with a history, so the extra sensitivity is visible.
8. Fill it before the event. Replay our recording and the Danish archive year through the scorer, so every ship seen before arrives with a history.

## Where things run

Proposed, not yet confirmed:
- Umbrel records and runs the live scorer. Once a minute it pushes one small JSON file to an Apache server.
- The Apache server serves a static page that reads the JSON. PHP is at most a small receiver for the upload. No scoring in PHP.
- Profiles are fitted on the PC and shipped to Umbrel as JSON files.
- Nothing at home accepts inbound connections.

## Slices - before the event

Preparation is recording and profile research. No Copernicus, nothing user-facing. If anything new is built before the event, add it to PRIOR_WORK.md the same day.

| # | Slice | State |
|---|---|---|
| P0 | Recorder, gap ledger, verify | done, running |
| P0b | Hourly backup pull to the PC | done |
| P1 | Registration | done. Email about solo and prep still open |
| P2 | Reality checks | AIS interval done (about 10 s). Cable geometry open. Copernicus archive open (a look at the catalogue, no download) |
| P3 | Static data: sanctions CSV, cables, pipelines | open |
| P4 | Loader, tracks, journeys | done, `alibi_lab/` |
| P5 | Profiles: prototype, own, journey, tracker | first version done, lab 02. Re-fit as data grows |
| P6 | Real-case evaluation | Eagle S done, lab 03. Fitburg (31.12.2025) would be a second case, track needs another source |
| P7 | Place: tiles into the tracker, white space table | tiles started in lab 01, not in the tracker yet |
| P8 | Working-vessel classes, pilot boarding events, position quality | open |
| P9 | Re-run all tests on two to three weeks of data | open, around Oct 22-27 |

Collisions: Käyrä build Oct 12-18, element14 application Oct 17-18, Puolisko video. P7 is the one that must not slip past Oct 22.

## Slices - during the event

| # | Slice | When |
|---|---|---|
| H0 | Copernicus connection: pull physics and waves (and wind) for the recorded weeks and the forecast, join to tracks, speed through water | Day 1, first |
| H1 | "Does the sea explain it" score: weather response per class, fitted on the recorded history | Day 1 evening |
| H2 | Live scorer on Umbrel, JSON push | Day 1 night |
| H3 | Map page: heat layer, ship markers, icons | Day 2 morning |
| H4 | Ship card: track, expected against actual, factor list, confidence | Day 2 |
| H5 | Sanction icon, working-vessel icons, infrastructure layer | Day 2 |
| H6 | Replay of the best recorded cases as the demo | Day 2 evening |
| H7 | Pitch materials, test numbers, limits slide | Day 3 before 10:00 |

Day 1 carries the most risk now. The whole Copernicus part starts from zero at 16:00, and H1 depends on past weeks being downloadable.

Checkpoint 1 says plainly what existed before the event: the recording and the profile research. Everything Copernicus and everything on screen is built in the window. That is the progress story and it is true.

## Cut order

1. "Looks like a boarding, no second vessel" label.
2. Infrastructure layer.
3. White space factor.
4. Weather regression (fall back to "was the sea rough here, yes or no" - still Copernicus).
5. Live feed (replay of recorded days is still a complete demo).

Never cut: the recording, the gap ledger, the Copernicus join, the test numbers, the separation of scores from the icons.

## Responsible use

No live alerts. Alibi is not an intrusion detector for the sea. There is no alert feed, no siren, no "anchor dragging detected", no "cable sabotage". Ships are ranked, least explained first, and coloured. Even at the top of the scale the sentence is "behaving unusually, and weather, place, traffic and its own history do not explain it". Alibi cannot judge intent and says so. A person decides what it means.

Why single-signal alerts fail, measured in our own data (for the documentation, stated as facts, not as criticism of anyone):
- The AIS status field is whatever the crew last selected. In one week of our recording (Oct 10-16, 21 M positions) 134 ships reported "at anchor" while moving at 3 kn or more, 13.5 % of all anchor reports. A rule "anchored and moving = anchor dragging" would fire about 19 times a day in the Gulf of Finland alone.
- The real case says the opposite. Eagle S broadcast "Under way using engine" the whole time it dragged its anchor across the cables (12 -> 9 -> 6 kn, 10:13-11:49 UTC), and still while drifting with the engine stopped. A status rule misses it.
- 160,000 positions in the same week report over 50 kn: SAR aircraft and position errors. Impossible speeds belong to position quality, never to behaviour.
- So the status field never triggers anything. A mismatch between status and behaviour is at most a minor data-hygiene note in the evidence.

Acceptance test for the event, one measured statement:
- Replay every recorded day: how many ships reach the top band, each with its evidence. Target: none, or a stated handful, each one explainable on inspection.
- Replay Eagle S: reaches the top band at +X minutes, before Estlink 2 (+13 min).
Tune until both hold. Both numbers go into the pitch.

- Unusual is not guilty. The interface says so on the map, not in a footnote.
- No free text about a named ship from a model. Fixed sentences only.
- Listings shown in two clearly separate kinds, each with its source and date, matched by IMO:
  - Sanctioned: EU designated vessels (Council Regulation 833/2014, list from dma.dk). A legal decision.
  - Listed by Ukrainian military intelligence (GUR "War & Sanctions", via OpenSanctions): one party's assessment, with its stated reason (shadow fleet, military logistics, ...). Never labelled "sanctioned".
  A listing is evidence about the ship, not about its behaviour. It raises the risk weight; it never makes a ship unexplained by itself.
- Later (not for the event): a settings panel to switch evidence sources on and off and change their weights. Every score then states which sources and weights produced it, so a changed setting is visible in the evidence trail, and the default set is what the published numbers were measured with.
- Limits published with the tool: coverage area, weeks of history, storms seen, no ice season in the data, one real case behind the thresholds.
- Eagle S data is third party. Show the result, not the data, unless the source's terms allow more.

## Reuse

- `Apps\Virta`: `scoring.py` for named-factor scoring, `archive.py` and `replay.py` for recorded-to-live.
- `Apps\Whyf`: `check_secrets.py`, `check_publishable.py`, Makefile targets, README and SECURITY precedent.

## Risks

- Solo not accepted. Answered by one email.
- Copernicus past fields not retrievable. Then there is no weather for the recorded weeks and H1 has nothing to fit on. Check the catalogue before Oct 22.
- Day 1 overload. See cut order.
- Too little weather in three and a half weeks. Say it, show the confidence, do not pretend.
- Thresholds rest on one real case and little data. Re-fit in P9 and report the trade-off curve, not one number.
- Flags pile up near stops. Place context (P7) is the fix and must be in before the event.
