# ALIBI video script

About 3 minutes. Screen recording of https://helppox.com/alibi/ (or localhost) with voice over. Each scene has a link that opens the GUI in the right state, so nothing has to be clicked live. Open each link once before recording: the first load of a case can take up to a minute, after that it is fast.

Links (helppox; for local use http://127.0.0.1:8600/ instead):

- L1 recorded day: https://helppox.com/alibi/#case=fi_replay_2026-10-26&src=profile
- L2 same day, all on: https://helppox.com/alibi/#case=fi_replay_2026-10-26
- L3 storm, sea state switched on: https://helppox.com/alibi/#case=dk_feb2026&src=profile,own_habit,place,fleet,notices,position_quality,identity,ice&then=sea_state&sel=GRIFTBOR
- L4 Gulf of Finland fleet slowdown: https://helppox.com/alibi/#case=fi_fleet_2026_10_05&src=profile,own_habit,place,fleet,notices,position_quality,identity,ice&then=sea_state
- L5 Eagle S (local only, the data is not ours to publish): http://127.0.0.1:8600/#case=eagle_s_2024&sel=EAGLE
- L6 Swagger: https://helppox.com/alibi/api/v1/docs
- L7 live: https://helppox.com/alibi/#case=live_gof

---

## 1. Why (0:00-0:30)

**Screen:** title card, ALIBI and "Automatic Lookout for Irregular Baltic Itineraries". Then L1 loading.

**Voice:**
I'm Juha. My background is IT security. Security dashboards have a known problem: false positives. When a dashboard flags ordinary things all day, people stop reading it. Antivirus used to look only for known fingerprints. Now it measures deviation from normal. I wanted to see if the same works at sea, for things like anchor dragging over cables.

## 2. The problem (0:30-0:55)

**Screen:** L1, profile only. The board is full of red rows.

**Voice:**
This is one ordinary day in the Gulf of Finland. A simple detector, the kind existing tools use, flagged 138 slowdowns and stops. With only the ship profiles behind it, 128 of them look unexplained. Nobody reads that list.

## 3. The idea (0:55-1:20)

**Screen:** L2, all sources on. Point at the top-band counter and the factor lamps.

**Voice:**
ALIBI does not try to find suspicious ships. It tries to explain them. The place: is this a berth or an anchorage, a speed limit? The ship's own habits. The traffic around it. And the sea. Same day, all sources on: about 20 are left. The unexplained is the interesting batch. The sea is the alibi.

## 4. Copernicus (1:20-1:55)

**Screen:** L3. Let the strip animate "13 -> 9 WITH SEA STATE ON". Recognition sheet of GRIFTBOR: sea state "explains about 82 %", wind 15.5 m/s, waves 2.8 m.

**Voice:**
My hypothesis was that weather explains a lot of strange behaviour. I tested it first: 48,000 ship segments against Copernicus Marine wind and waves. In calm sea 15 % of ships run clearly slower than usual. At 14 m/s wind it is 48 %. So in a storm, switching on sea state takes ships off the list. This one, in the Danish straits in February, slowed from 9 to about 4.5 knots. Copernicus says wind 15 m/s and almost 3 m waves explain most of it.

## 5. Eagle S (1:55-2:20)

**Screen:** L5 (local). Sheet: Unusual 73, Unexplained 70, sea state "about 0.1 kn, little next to the 3.7 kn slowdown". Point at the trace leaving the band.

**Voice:**
And the opposite. Eagle S, Christmas 2024, before Estlink 2 went offline. The detector flags the slowdown 8 minutes after it starts, before the cable. ALIBI checks the sea: it explains 0.1 knots of a 3.7 knot drop. So it stays on top of the list. ALIBI does not say why. It says: behaving unusually, and the available evidence does not explain it.

## 6. It is middleware (2:20-2:40)

**Screen:** L6 Swagger, "POST /assessments", try it out with the example. Then L7 live board.

**Voice:**
The GUI is only a demo. ALIBI is an API: any AIS system can send an event and get back the two numbers, the evidence per source and the settings used, all logged. It runs live on Finnish AIS, with profiles from two years of Danish archive data and our own recording, refreshed every night.

## 7. Limits and close (2:40-3:00)

**Screen:** About / Limits overlay. End card: repo and demo URL.

**Voice:**
It is a prototype. The thresholds rest on few real cases, and about 20 a day is still more than I want. Unexplained is not proof of anything: everyone is innocent until proven otherwise. ALIBI just processes the information and shows it.

**End card:** github.com/apn201/Alibi | helppox.com/alibi | Generated using E.U. Copernicus Marine Service Information.

---

Numbers used above, for checking: README.md "Proof of value" and eval/results/proof.md (2026-10-26: 138 candidates, 20 in the top band with all sources; dk_feb2026 13 -> 9 with sea state; Eagle S flagged +8 min at sensitivity 0.5, sea explains 0.1 of 3.7 kn), eval/results/hypothesis.md.
