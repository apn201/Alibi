# ALIBI - AIS recorder, build spec for Claude Code

Written 2026-10-04. First piece of Alibi (Copernicus Marine Service Hackathon 2026, Oct 29-31).

Alibi scores how well the sea explains what a ship is doing. That needs a history of what ships did. The AIS feed is live only, so the history has to be recorded, starting now. This spec is the recorder and nothing else.

Every day not recorded is a day of baseline that cannot be bought later.

## Job

Connect to the Fintraffic Digitraffic marine feed. Write every message to disk, untouched, with the time it arrived. Survive disconnects, restarts and full weeks unattended. Know its own gaps.

No analysis. No filtering. No database. Capture first, think later.

## Source

Verified from digitraffic.fi/en/marine-traffic on 2026-10-04.

- MQTT over WebSockets, TLS. Host `meri.digitraffic.fi`, port 443. Address `wss://meri.digitraffic.fi:443/mqtt`.
- Subscribe to `vessels-v2/#`. One subscription covers locations, metadata and status.
- The docs spell the location topic both `location` and `locations`. Do not hardcode either. Subscribe to the wildcard, store the topic string as received, parse the MMSI and kind from it.
- Client id: `"<APP_NAME>; <uuid4>"`, APP_NAME like `apn201/alibi-recorder 0.1`. Python: `paho-mqtt`, `CallbackAPIVersion.VERSION2`, `transport="websockets"`, `tls_set()`.
- `vessels-v2/status` carries `{"updated": <epoch s>}`. Use it as the feed heartbeat.

Location message:
```
{"time":1668075025,"sog":10.7,"cog":326.6,"navStat":0,"rot":0,
 "posAcc":true,"raim":false,"heading":325,"lon":20.345818,"lat":60.03802}
```

Metadata message:
```
{"timestamp":1668075026035,"destination":"UST LUGA","name":"ARUNA CIHAN",
 "draught":68,"eta":733376,"posType":15,"refA":160,"refB":33,"refC":20,
 "refD":12,"callSign":"V7WW7","imo":9543756,"type":70}
```

Trap: location `time` is epoch seconds, metadata `timestamp` is epoch milliseconds. The recorder does not convert. It just must not break on it.

REST, for the fallback and the daily snapshot:
- `https://meri.digitraffic.fi/api/ais/v1/locations`
- `https://meri.digitraffic.fi/api/ais/v1/vessels`
- Send header `Digitraffic-User: apn201/alibi-recorder 0.1` and `Accept-Encoding: gzip`.
- Read digitraffic.fi/en/support/instructions (General considerations) for rate limits before choosing poll intervals. Do not guess them.

Coverage is what Finnish receivers hear: Gulf of Finland, Archipelago Sea, Gulf of Bothnia, northern Baltic proper. Not the whole Baltic. That is the honest scope and the report will say so.

## Output

Append-only JSONL, one line per message, wrapped not altered:

```
{"rx": 1791234567.123, "topic": "vessels-v2/230123456/location", "payload": { ...as received... }}
```

- `rx` = local receive time, epoch seconds float, UTC. Host clock must be NTP-synced. Log a warning at start if it cannot be confirmed.
- If a payload is not valid JSON, store it as a string under `raw` instead of `payload`. Never drop a message.
- Files: `data/ais/YYYY/MM/DD/ais-YYYYMMDD-HH.jsonl`, UTC hours. On rotation, gzip the closed hour and write a `.sha256` beside it.
- Flush at least every 5 s. A power cut may cost seconds, not an hour.
- Never rewrite or delete a closed file. No dedup at capture.
- Where a jsonl convention already exists in `Apps\Virta` (`virta/archive.py`, `virta/replay.py`), match it so replay drops in later. Read those two files first.

## Gap ledger

Silence in the data must mean a quiet sea, not a dead recorder. So gaps are recorded as facts.

`data/ais/gaps.jsonl`, one line per event:
```
{"ts": ..., "event": "start|stop|connect|disconnect|stale|resume|fallback_on|fallback_off", "detail": "..."}
```

- `stale`: no message of any kind for 120 s while connected. Force a reconnect.
- On disconnect: reconnect with backoff 1 s to 60 s, jittered, forever.
- Clean shutdown on SIGINT/SIGTERM writes `stop`. A missing `stop` before the next `start` means a crash - log it on startup.

## REST fallback and snapshots

- While MQTT has been down for more than 5 minutes, poll `/locations` at a polite interval (per the rate limits) and store each response whole as `data/ais/rest/locations-<ts>.json.gz`. Stop when MQTT is back.
- Once a day, store `/vessels` whole as `data/ais/rest/vessels-<date>.json.gz`. This is the name, IMO and type table, cheap insurance against missed metadata messages.

## Operations

- Python 3.11+. Dependencies pinned. One process, one config file, env overrides.
- Dockerfile plus compose with `restart: unless-stopped`, data dir as a volume. Must also run bare with `python -m alibi_recorder`.
- Runs on an always-on box, not the dev laptop.
- Stats line to stdout every 60 s: messages per minute by kind, unique MMSI in the last hour, bytes written today, projected GB per day, free disk.
- Free disk below 5 GB: loud warning every minute. Below 1 GB: stop writing, log the gap, keep the process alive.
- `alibi-recorder verify <dir>`: checks gz integrity and sha256 for every closed file, lists hours with no file, prints total coverage percent since first start.
- No secrets exist in this component. Keep it that way.

## Tests

- Parse the two sample messages above, both topic spellings.
- Rotation at the hour boundary: no lost line, no line in two files.
- Kill -9 mid-write, restart: file still parses up to the last flushed line, crash is logged in the gap ledger.
- Fake broker that goes silent: `stale` fires, reconnect happens.
- Disk-full path.

## Out of scope here

Scoring, baselines, heatmap, Copernicus downloads, cable and pipeline geometry, vessel lists. All of that reads these files later. None of it belongs in the recorder.

## Done when

1. It has run 24 h unattended and `verify` reports the coverage.
2. The first-hour stats give a real GB-per-day number, so the disk can be sized for 4 weeks.
3. One recorded hour can be read back line by line with ten lines of Python.
