# Submission post

Ready to paste. Short fields first, then the description. Longer story: [submission.md](submission.md).

**Project name:** ALIBI

**Tagline:** The sea is the alibi. A second opinion for maritime monitoring that explains unusual ship behaviour before a human has to look at it.

**Challenge:** Enhancing Maritime Security and Resilience

**Team:** Juha Lilja (APN201), solo

**Links**
- Demo: https://helppox.com/alibi/
- API (Swagger): https://helppox.com/alibi/api/v1/docs
- Code: https://github.com/apn201/Alibi
- Video: [add link]

## Description

ALIBI (Automatic Lookout for Irregular Baltic Itineraries) is middleware for AIS monitoring. An existing system flags a ship that does something unusual, for example a slowdown over a cable. ALIBI tests what could explain it: the sea, the place, the ship's own habits and the traffic around it. It returns two separate numbers, Unusual and Unexplained, with the evidence per source and the confidence. The unexplained is the short list worth a human's time.

I come from IT security. Dashboards full of false positives stop being read. Antivirus moved from known fingerprints to deviation from normal, and I wanted to try the same at sea. ALIBI does not accuse anybody: "behaving unusually, and the available evidence does not explain it" is the strongest thing it says.

**Copernicus Marine data used:** Baltic Sea wave analysis and forecast (wave height and direction), Baltic Sea physics (surface currents, sea ice), global hourly L4 sea-surface wind. Wind and waves give the expected speed loss (Kwon's method), currents the change in speed over ground, ice its own explainer. Fields are fetched once per area and hour into a shared cache, never per request.

**Results, measured:**
- Hypothesis test, 47,893 ship segments: in calm sea 15 % of merchant ships run clearly below their usual speed, at 14 m/s wind 48 %, at 2.5 m waves 51 %.
- An ordinary recorded day: 126 detector candidates, about 22 left in the top band with all sources on.
- Storm cases: Copernicus takes 10 to 30 % more off the top band. On calm days it changes almost nothing.
- Eagle S (Christmas 2024): flagged 8 minutes after the slowdown began, before Estlink 2. The sea explains 0.1 of its 3.7 knot drop, so it stays unexplained.

**Other data:** Fintraffic Digitraffic AIS (recorded live since 4 Oct 2026), Danish Maritime Authority AIS archive (Oct 2024 to Oct 2026), Traficom restriction areas and navigational warnings, EU sanctions list and the GUR listing as identity context only (never in the score).

**Built with:** Python, FastAPI, pandas, DuckDB, xarray, Copernicus Marine Toolbox; plain HTML/JS for the console. Runs on one small server behind Apache.

**Limits:** prototype; thresholds rest on few real cases; about 22 a day is still more than wanted; Copernicus fields are hourly and about 2 km. Copernicus Marine products cannot see ships with AIS off (checked: [dark-vessels-feasibility.md](dark-vessels-feasibility.md)).

Generated using E.U. Copernicus Marine Service Information.

## Screenshots

In `docs/screenshots/`:

1. `01-fleet-slowdown-sea-state-on.png`: Gulf of Finland fleet slowdown, 5-6 Oct 2026, the moment sea state is switched on (top band 53 to 49).
2. `02-eagle-s.png`: Eagle S, the slowdown that stays unexplained, with the recognition sheet.
3. `03-denmark-feb2026-storm.png`: Danish straits storm, Feb 2026, top band 13 to 9; GRIFTBOR from 99 to 18, the sea accounts for about 82 %.
4. `04-recorded-day.png`: an ordinary recorded day, all sources on.
5. `05-profile-only.png`: the same day with only the profiles: the list nobody reads.
6. `06-swagger.png`: the API.
7. `07-hypothesis.png`: share of slow ships against Copernicus wind and wave height.
