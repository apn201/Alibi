# Build spec (hackathon, 2026-10-29 → ship Fri 2026-10-30 12:00)

Internal working document for everyone building in this repo. The product is described in
`ALIBI-design-brief.md`, the plan in `alibi-plan.md`; where this file and the plan disagree, the plan wins.
Python: `.venv/Scripts/python.exe` (3.14). Set `PYTHONUTF8=1` on Windows.

## Layout and ownership

| Path | What | Owner |
|---|---|---|
| `alibi/` | The ALIBI service (the product). FastAPI. | core |
| `alibi/env/`, `alibi/explainers/sea_state.py`, `tools/fetch_copernicus.py` | Copernicus environmental cache and the sea-state explainer | copernicus |
| `rules/` | Shared detector rule library (used by `detector/` AND by ALIBI track mode) | detector |
| `detector/` (minus `web/`) | Demo AIS tool: builds replay cases, runs rules, calls ALIBI over HTTP | detector |
| `detector/web/` | GUI (signature board), static HTML/JS, a client of the ALIBI API | gui |
| `eval/` | Proof-of-value runs | later |
| `docs/` | Docs | lead |

Do not edit files owned by someone else. If you need a change in another part, write it in your final report.
Never commit or copy anything from `data/` into tracked paths (third-party data, our recording).

## Data the code reads (all git-ignored, read-only)

- Profile DB `data/derived/profile_db/`: `vessel_profiles.parquet` (per `vessel_key`, `source` in all/dk/fi;
  columns speed, speed_iqr, crab, turn, *_spread, hours, segments, name, cls, imo), `class_profiles.parquet`
  (per `cls` like `cargo/L`), `vessel_keys.parquet` (mmsi → vessel_key, imo, name, group, length, cls),
  `segments/{dk,fi}/YYYY-MM-DD.parquet` (one row per moving segment: mmsi, t0, t1 epoch s, lat, lon median,
  speed median kn, speed_iqr, crab, turn). dk = Danish archive 2024-10-01..2026-10-17, fi = our Gulf of Finland
  recording 2026-10-05..2026-10-28. Profile version string: `pdb-2026-10-28`.
- Lab code to reuse: `alibi_lab/profiles.py` (Profile, blend constants, JourneyTracker, the lab-03 rule pair),
  `alibi_lab/load.py` (our recording → locations), `alibi_lab/external.py` (Eagle S reader),
  `alibi_lab/dma.py` (`F:/alibi-data/dma/positions/YYYY/aisdk-*.parquet`, one position per ship per minute).
- Sanctions: `data/external/sanctions/dma_eu_designated_vessels_2026-07-24.csv` (EU, by IMO),
  `data/external/sanctions/opensanctions_ua_war_sanctions_entities.ftm.json` (GUR via OpenSanctions).
- Context: `data/context/` (restriction areas incl. anchoring bans, nav warnings, fairways, waterway signs;
  Finnish waters only). `data/context/index-umbrel.jsonl` lists every snapshot.
- Copernicus cache: `data/envcache/` (written by `tools/fetch_copernicus.py`).

## Wire format (the contract)

`alibi-openapi.yaml` is the contract. Request = `AssessmentRequest`, response = `Assessment`.
Additions made today (core updates the YAML):

- `Assessment.signature` (optional object), for the GUI trace: equal-length arrays over 1-minute steps
  `t` (ISO UTC), `observed_kn`, `expected_profile_kn`, `band_profile_kn` (half-width), `expected_adjusted_kn`,
  `band_adjusted_kn`, `state` (0 inside band, 1 outside profile band but inside adjusted band = unusual explained,
  2 outside adjusted band = unexplained), and `event_start`/`event_end`.
- `Assessment.vessel` (optional): `{vessel_key, mmsi, imo, name, cls, profile_tier: own|prototype|journey|working}`.
- `Assessment.lamps` (optional): `{WX, ICE, PLC, GNSS, TRF}` each `explains|not_explained|neutral|unavailable`.
- `GET /api/v1/sources` → list of source ids with title, kind (`behaviour|quality|identity`) and attribution.

Source ids (use exactly these): `profile` (always on, the baseline), `sea_state` (Copernicus), `ice`,
`own_habit`, `place`, `fleet`, `notices`, `position_quality`, `identity`.

### Case files (detector → GUI and eval)

`detector/cases.py` writes `data/cases/<case_id>.json`:
```json
{"case_id": "eagle_s_2024", "title": "...", "kind": "known_case|fleet_slowdown|counter_example|replay_day",
 "region": "gof|dk", "start": "...Z", "end": "...Z", "third_party": true,
 "requests": [AssessmentRequest, ...]}
```
One AssessmentRequest per candidate event, each with its own `track` (6 h before the event end, 1-minute
resolution) and `event` from the rules (or `event` omitted for track mode). `metadata` carries
`{"case_id", "vessel_name", "ship_type", "length_m", "imo"}` when known.

## Scoring (shared semantics; core implements)

- **Unusual** U ∈ [0,1]: ALIBI's own second opinion. Expected speed = blend of own profile, class prototype and
  this journey (pre-event part of the track), as in `alibi_lab/profiles.py`. Drop d = (expected − observed)/expected
  over the event window (median SOG). Scale σ = max(ship's own steadiness, 0.3 kn). U = 1 − exp(−max(0, z − 1)/3)
  blended with the relative drop, documented in code. Working vessels (tug, pilot, SAR, pleasure, fishing, service)
  are `profile_tier=working`, U and unexplained null, not scored.
- Each behaviour explainer returns a Finding with `explains` e ∈ [0,1] = share of the deviation it accounts for,
  and a status: `supports_explanation` (e ≥ 0.2), `weakens_explanation` (checked and found the opposite, e.g. calm sea),
  `neutral`, `unavailable` (no data: lowers confidence, never raises anything).
- **Unexplained** X = U × Π(1 − eᵢ) over enabled behaviour explainers. X ≤ U always.
- Quality explainers (`position_quality`) only change confidence. Identity (`identity`) is always
  `identity_context_only`, never touches U or X. EU designation and GUR listing are two separate findings,
  never call a GUR listing "sanctioned".
- **Confidence** high/medium/low with reasons: missing sources, cold-start profile, short track, poor position quality.
- **Sensitivity** s ∈ [0,1] (default 0.5): top band if X ≥ 0.75 − 0.5·s. Recorded in the result.
  In the detector, s maps to the rule thresholds (s=0 conservative ×0.7 rule only, s=1 adds the 4σ+10 % rule
  and shorter windows).
- Every result records `api_version`, `model_version` (`alibi-0.1.0`), `profile_version`, enabled sources,
  sensitivity, `detected_by`.

## Language rules (all user-facing text)

Fixed, human-written sentences only; the code picks which applies and fills numbers. Never "threat",
"suspect", "guilty", "incident", "sabotage", "anchor dragging". Allowed: unusual, explained, unexplained,
evidence, confidence. Top of the list reads "behaving unusually, and the available evidence does not explain it".
No LLM in the decision path. The AIS nav status never triggers anything.

## Ports

ALIBI API `127.0.0.1:8601` (`python -m alibi`), base path `/api/v1`, Swagger at `/api/v1/docs`.
Detector/GUI static server `127.0.0.1:8600` (`python -m detector serve`). GUI reads `ALIBI_API` from
`detector/web/config.js` (default `http://127.0.0.1:8601/api/v1`). Under Apache both sit under one origin:
`/alibi/` (GUI) and `/alibi/api/v1/` (API).
