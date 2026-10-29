# ALIBI

ALIBI (Automatic Lookout for Irregular Baltic Itineraries) is a second opinion for maritime monitoring. An AIS system flags a ship that does something unusual. ALIBI checks whether the sea, the place, the ship's own habits or the traffic around it explain it. What is left unexplained is the short list worth a human's time.

The sea is the alibi.

Built for the Copernicus Marine Service Hackathon 2026, challenge Enhancing Maritime Security and Resilience. Solo entry. Why I built it: [docs/submission.md](docs/submission.md).

Demo: https://helppox.com/alibi/ | API: https://helppox.com/alibi/api/v1/docs

## What it is

Two separate parts that talk over HTTP only:

- **Demo AIS detector** (`rules/`, `detector/`). A stand-in for whatever AIS system you already have. Stateless rules over one ship's track: slowdown against its own journey, the Eagle S pattern (steady cruise, then a sustained drop with course held), a grounding pattern, AIS gaps, slow passage in a cable corridor. It over-flags on purpose.
- **ALIBI** (`alibi/`). The product. A REST API that takes an event and its track and returns an assessment: **Unusual** and **Unexplained** as two separate numbers, confidence with reasons, and one finding per source with its evidence. Every result records the API, model and profile versions, the sensitivity and the enabled sources. Results go to an audit ledger.

The GUI (`detector/web/`) is just one client of the API. The same call works with curl, see [examples/](examples/).

## Sources

| Source | What it can explain | Data |
|---|---|---|
| Sea state | wind and waves slow a ship (Kwon's speed-loss method), current changes speed over ground | Copernicus Marine: Baltic waves, Baltic physics, global L4 wind |
| Ice | ice concentration and thickness | Copernicus Marine Baltic physics |
| Own habit | this ship always runs slower here | profiles from AIS history |
| Place | ships of this kind are slower here, speed limits, berths and anchorages where ships stop | profiles, stop areas learnt from AIS, Traficom restriction areas |
| Fleet | everybody around slowed down too | AIS history |
| Notices | navigational warnings in force | Traficom |
| Position quality | lowers confidence only | the track itself |
| Identity | EU designation and GUR listing, shown separately, never part of the score | EU list (via DMA), OpenSanctions |

Missing data lowers confidence. It never raises suspicion.

## Does the sea explain anything?

Before using Copernicus as an explainer I tested it. 47,893 moving segments of 3,957 merchant ships, each compared with the same ship's usual speed, joined with Copernicus wind and waves at the time and place ([eval/results/hypothesis.md](eval/results/hypothesis.md)):

| Wind 10 m | share of segments below 85 % of the ship's own usual speed |
|---|---|
| under 5 m/s | 15 % |
| 8-11 m/s | 20 % |
| 11-14 m/s | 28 % |
| 14 m/s and more | 48 % |

Waves show the same: 17 % below 0.5 m, 51 % at 2.5 m and more. So yes, the sea explains a lot of slowing. It is association, not proof: storms also change routes and schedules.

## Proof of value

Same cases, same profiles, sensitivity 0.5. "Top band" is what a person would look at first. Full table and the ships that moved: [eval/results/proof.md](eval/results/proof.md).

| case | detector alone | top band, AIS-only explainers | + Copernicus | + everything |
|---|---|---|---|---|
| Eagle S, 25 Dec 2024 | 2 | 1 | 1 | 1 |
| TERRY grounding, Oresund 2012 | 1 | 1 | 1 | 1 |
| Gulf of Finland fleet slowdown, 5-6 Oct 2026 | 211 | 53 | 49 | 49 |
| Danish waters, storm 3-6 Oct 2025 | 60 | 16 | 14 | 14 |
| Danish waters, storm/ice 1-7 Feb 2026 | 60 | 13 | 9 | 9 |
| Danish waters, 2-4 Jul 2026 | 60 | 13 | 11 | 11 |
| Recorded days 25-28 Oct 2026 (average) | 126 | 24 | 22 | 22 |

What it shows, honestly:

- Most of the reduction comes from the place and the ship's own habits (arrivals at berths and anchorages). On an ordinary day ALIBI takes the detector's 126 candidates down to about 22.
- Copernicus moves individual ships a lot when the weather is bad: in the 5-6 Oct case THEIA went from Unexplained 0.87 to 0.20 (wind 14.5 m/s, waves 3.4 m), in Feb 2026 KOBE PIONIER from 0.96 to 0.12. In the top-band count it is 10 to 30 % on stormy cases and close to nothing on calm days.
- Eagle S stays in the top band. Copernicus accounts for about 0.1 kn of its 3.7 kn drop (wind 10.9 m/s from behind). At sensitivity 0.5 the detector flags it 8 minutes after the drop began, before Estlink 2 (13 minutes). The conservative setting takes 59 minutes.
- July 2026 was planned as the calm counter-example. It turned out to have 14 m/s winds on 2-3 July, so Copernicus explained some of it too.
- About 22 a day in the top band is still more than "a handful". The rest are mostly long slow passages (ships slowing for hours, likely timing their arrival) that no source here can explain yet.

## Run it

Python 3.12+ (developed on 3.14).

```
python -m venv .venv
.venv/Scripts/pip install -r requirements-service.txt     # Linux: .venv/bin/pip
python -m alibi                                            # API on 127.0.0.1:8601, Swagger at /api/v1/docs
python -m detector serve                                   # GUI on 127.0.0.1:8600
```

A plain clone runs: the profiles, the Copernicus data for the replay cases, the replay cases and the reference lists are in `snapshot/`. Raw AIS is not in the repo; the history lives in the profiles.

Other commands:

```
python -m detector cases                      # rebuild replay cases from local AIS data
python -m detector live --ais-dir data/ais    # live Gulf of Finland case from the recorder, every 10 min
python -m alibi_recorder                      # record the Digitraffic AIS feed
python tools/fetch_copernicus.py --recent 3   # needs `copernicusmarine login` once
python tools/nightly.py --push                # new AIS days, profiles, stop areas, snapshot, push
python eval/hypothesis.py                     # the sea-state test above
python eval/proof.py                          # the proof-of-value table
```

Deploying on Apache: [deploy/](deploy/) has the systemd units, the Apache snippet and a step-by-step prompt ([deploy/openclaw-prompt.md](deploy/openclaw-prompt.md)).

## Keeping profiles fresh

Nightly job (`tools/nightly.py`, Windows task "Alibi nightly profiles" at 03:30): ingest new days of the Danish archive, rebuild profiles leaving out windows ALIBI could not explain (do not learn from what you flag), rebuild stop areas, fetch recent Copernicus data, refresh `snapshot/`, commit and push. The server pulls at 06:00. Every assessment records the `profile_version` it used, so an old result can be reproduced.

Live AIS: Fintraffic Digitraffic for Finnish waters (MQTT, recorded continuously). Denmark publishes its AIS as a daily archive, not live, so Danish waters update once a day.

## Limits

- No live alerts. ALIBI ranks; it does not alarm. "Behaving unusually, and the available evidence does not explain it" is the strongest thing it says. Unexplained is not evidence of intent.
- Sentences are fixed and written by people. No language model is anywhere in the decision path.
- AIS coverage: our own recording of Finnish waters from 2026-10-05, and the Danish archive (Skagerrak to Bornholm) from 2024-10-01. The Gulf of Finland in December 2024 (Eagle S) is outside both, so for Eagle S only the profile, the sea and position quality can speak.
- The thresholds rest on few real cases: Eagle S, TERRY 2012 and the fleet slowdowns. The stop areas and own stops were learnt partly from the same days they are tested on.
- Copernicus model fields are hourly and about 2 km. They describe the sea around a ship, not at its bow. The Kwon speed-loss coefficients are a fit of the published table.
- The cable corridors are schematic straight lines with a stated uncertainty.
- AIS status ("at anchor", "under way") never triggers anything.

## Data and attribution

- Generated using E.U. Copernicus Marine Service Information (BALTICSEA_ANALYSISFORECAST_WAV_003_010, BALTICSEA_ANALYSISFORECAST_PHY_003_006, WIND_GLO_PHY_L4_NRT_012_004, WIND_GLO_PHY_L4_MY_012_006).
- AIS: Fintraffic Digitraffic marine AIS (CC BY 4.0), recorded by ALIBI; Danish Maritime Authority AIS archive (aisdata.ais.dk).
- Context: Traficom restriction areas, navigational warnings, waterway signs and fairways (CC BY 4.0).
- Identity: EU designated vessels under Council Regulation 833/2014 (list published by the Danish Maritime Authority, 2026-07-24); Ukrainian GUR "War & Sanctions" vessel listing as compiled by OpenSanctions (CC BY-NC 4.0). A GUR listing is one party's assessment, not a sanction.
- Eagle S voyage data: eagles-report.com, used for evaluation only and not in this repo.

What existed before the hackathon: [PRIOR_WORK.md](PRIOR_WORK.md). Ship detection without AIS from Copernicus data: [docs/dark-vessels-feasibility.md](docs/dark-vessels-feasibility.md). Licence: MIT.
