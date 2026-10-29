# Alibi - AIS recorder

Records the Fintraffic Digitraffic marine AIS feed (`vessels-v2/#` over MQTT/WSS) to disk, untouched. Original spec: [archive/recorder-spec-2026-10-04.md](archive/recorder-spec-2026-10-04.md).

The product: [ALIBI-design-brief.md](ALIBI-design-brief.md). How it gets built: [alibi-plan.md](alibi-plan.md). API contract: [alibi-openapi.yaml](alibi-openapi.yaml). What existed before the hackathon: [PRIOR_WORK.md](PRIOR_WORK.md). Superseded documents: `archive/`.

## Run

Docker (the normal way, restarts itself):

```
docker compose up -d --build        # data goes to $ALIBI_HOST_DATA (see .env), default ./data
docker logs -f alibi-recorder       # stats line every 60 s
docker exec alibi-recorder python -m alibi_recorder verify
```

Bare: `pip install -e .` then `python -m alibi_recorder` (or `alibi-recorder`), `alibi-recorder verify data/ais`.

Config: optional `alibi-recorder.toml` (keys in `alibi_recorder/config.py`), any key overridable as `ALIBI_<KEY>`.

## Output

- `ais/YYYY/MM/DD/ais-YYYYMMDD-HH.jsonl` - the open UTC hour; closed hours become `.jsonl.gz` + `.jsonl.gz.sha256`.
  One line per message: `{"rx": <epoch s UTC>, "topic": "...", "payload": {...}}`, or `"raw": "..."` if the payload was not JSON.
  The feed pretty-prints its JSON; only whitespace between tokens is removed, every value is byte-identical.
- `ais/gaps.jsonl` - `start stop connect disconnect stale resume fallback_on fallback_off`, plus
  `crash` (previous run had no `stop`; carries `last_rx`, the last line on disk) and `disk_pause` / `disk_resume`.
- Imported recordings from another recorder instance sit beside the hour they belong to as
  `ais-YYYYMMDD-HH-<source>.jsonl.gz` (+ `.sha256`), with their ledger as `ais/gaps-<source>-<date>.jsonl`.
  Hours can then hold overlapping lines from two recorders: readers take all files of an hour and dedup
  on (topic, payload). `verify` counts them and merges the ledgers' connected time.
  Case in point: the first hour (19:45-20:41 UTC) was recorded on the PC (`F:\alibi-data\ais`) before
  Umbrel took over at 20:40. Both are in `data/ais` now (see Backup): hour 20 exists twice,
  the PC's copy as a sibling.
- `ais/rest/vessels-<date>.json.gz` daily; `ais/rest/locations-<ts>.json.gz` every 60 s while MQTT is down > 5 min.

Read one hour:

```python
import gzip, json
with gzip.open("ais/2026/10/04/ais-20261004-20.jsonl.gz", "rt", encoding="utf-8") as fh:
    for line in fh:
        msg = json.loads(line)
        if msg["topic"].endswith(("location", "locations")):
            print(msg["rx"], msg["topic"].split("/")[1], msg["payload"]["lat"], msg["payload"]["lon"])
```

## Backup to the PC

`alibi-recorder pull SRC [DEST]` copies closed hours from another recorder's data folder
(e.g. a network share of Umbrel's `/External/btcdata/alibi-data`) into DEST, default
`data/ais` in this project, which lives in Dropbox. Each hour is checked against its `.sha256`
before it gets its final name; the open hour is skipped; nothing in DEST is ever replaced
(a differing file is reported as a conflict). The source ledger is mirrored as `gaps-<label>.jsonl`
(default label `umbrel`). Safe to run any number of times; then `alibi-recorder verify data/ais`.

`tools/pull_task.py` runs the pull and the verify every hour and logs to `data/pull.log`.
On the PC copy `verify` always reports one hour without a file: the open hour, which the pull skips.

`data/ais` already holds the PC's first hour: `ais-20261004-19.jsonl.gz`, `ais-20261004-20-pc.jsonl.gz`,
`gaps-pc.jsonl`, `rest/vessels-2026-10-04-pc.json.gz`.

## Limits respected

Digitraffic (support/instructions, read 2026-10-04): MQTT 5 connections/min/IP -> reconnects capped at 4/min;
REST V1 60 req/min/IP and responses cached ~60 s -> fallback polls every 60 s. `Digitraffic-User` and gzip on every request.

## Tests

`pip install -e ".[dev]"` then `pytest`.

## Lab

`alibi_lab/` reads the recorded hours into pandas (cached as parquet in `data/derived/`, disposable);
`tools/profile_db_task.py` brings the profile DB (`data/derived/profile_db/`) up to date incrementally, log in `build.log` there;
`lab/*.py` are notebooks in `# %%` form, executed to `.ipynb` with
`python tools/run_notebook.py lab/01_first_day.py`. Extra dependencies: `requirements-lab.txt`.

## Context recorder

`python -m alibi_recorder context` (the `context` service in the Umbrel stack) saves hourly snapshots of
context that is only published live: Traficom navigational warnings, Digitraffic winter navigation
(icebreakers, dirways, port restrictions) and port visits, Väylävirasto faults in aids to navigation;
and daily the previous day's port calls, restriction areas (incl. anchoring bans), waterway signs
(incl. cable signs) and VL1/VL2 fairways. Unchanged responses are not stored twice; `context/index.jsonl`
records every check. Files land in `/data/context` beside `/data/ais`; the hourly pull copies them to
`data/context/`, checked against the sha256 in the index. All sources CC BY 4.0.
