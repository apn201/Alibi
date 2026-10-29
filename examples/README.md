# Examples

`event-eagle-like.json` is an `AssessmentRequest` cut from ALIBI's own recording of the
Fintraffic Digitraffic AIS feed: a large cargo ship in the Gulf of Finland, 26 Oct 2026,
6 hours of track at 1-minute resolution (medians), running a steady ~11.5 kn and then
dropping to ~3 kn for the last hour. The track is real AIS; the identity is removed and
replaced by a synthetic one (MMSI 999999001, no IMO, "EXAMPLE VESSEL", cargo, 230 m), so
ALIBI judges it against its class prototype and the journey, not a named ship's history. The event (the last hour) is what an upstream AIS
system would flag. It is a demonstration of the API, not a finding about the ship: an
unexplained result means the evidence available to ALIBI does not account for the slowdown,
nothing more.

Start the service (from the repo root):

```sh
PYTHONUTF8=1 .venv/Scripts/python.exe -m alibi        # http://127.0.0.1:8601/api/v1, Swagger at /api/v1/docs
```

Then:

```sh
API=http://127.0.0.1:8601/api/v1

curl -s $API/health
curl -s $API/sources

# event mode: the event and its track
curl -s -X POST $API/assessments -H 'Content-Type: application/json' -d @examples/event-eagle-like.json

# fetch it again from the ledger (assessment_id from the answer above)
curl -s $API/assessments/asm_...

# re-run under other toggles without writing to the ledger
python -c "import json; r=json.load(open('examples/event-eagle-like.json')); \
print(json.dumps({'requests': [r], 'options': {'enabled_sources': ['sea_state', 'fleet'], 'sensitivity': 0.8}}))" \
  | curl -s -X POST $API/assessments/batch -H 'Content-Type: application/json' -d @-

# track mode: drop the event, ALIBI's reference detector finds it
python -c "import json; r=json.load(open('examples/event-eagle-like.json')); r.pop('event'); \
print(json.dumps(r))" \
  | curl -s -X POST $API/assessments -H 'Content-Type: application/json' -d @-
```

The answer carries `measures` (unusual, unexplained, band), `confidence` with reasons, one
`finding` per source, `lamps`, the `signature` trace for the GUI and `audit_reference` into
the ledger (`data/alibi-ledger.sqlite`).
