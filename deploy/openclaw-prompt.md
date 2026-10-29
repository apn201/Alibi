# Prompt for OpenClaw: deploy ALIBI to helppox.com

Copy everything below the line into OpenClaw. The repo (github.com/apn201/Alibi) is private, so
OpenClaw will make a read-only deploy key and show you the public half; add it under the repo's
Settings > Deploy keys (read access only). If you make the repo public, skip that step.

---

You are deploying a small demo service called ALIBI to my Apache web server for the domain
helppox.com. It is a hackathon demo that must be reachable at https://helppox.com/alibi/ by
Friday 2026-10-30 12:00 Finnish time. Work carefully: this server hosts other sites, and none of
them may break.

## What ALIBI is

Everything comes from one git repository, `git@github.com:apn201/Alibi.git` (branch `main`). The
repo holds the code and all the data the service needs (`snapshot/`: ship profiles, Copernicus
cache for the replay cases, replay cases, reference lists). A fresh clone runs without anything
else. Processes, all bound to 127.0.0.1:

| Unit file in `deploy/` | What | Port |
|---|---|---|
| `alibi-api.service` | ALIBI assessment API (FastAPI/uvicorn), `python -m alibi` | 8601 |
| `alibi-gui.service` | GUI and replay cases, `python -m detector serve` | 8600 |
| `alibi-recorder.service` | records live AIS from Fintraffic Digitraffic (public MQTT, outbound wss to meri.digitraffic.fi:443) | none |
| `alibi-live.service` | builds the live Gulf of Finland case every 10 min from the recording | none |
| `alibi-warm.service` | runs the replay cases through the API once after start, so the GUI is fast | none |
| `alibi-update.service` + `.timer` | daily 06:00: `git pull`, pip install, delete raw AIS older than 3 days, restart | none |
| `alibi-copernicus.service` + `.timer` | every 6 h: fetch recent Copernicus Marine data (needs a login, step 8) | none |

Apache keeps HTTPS and reverse-proxies `/alibi/api/` to 8601 and `/alibi/` to 8600
(`deploy/apache-alibi.conf`).

## Steps

1. Look before you change anything. Report: OS and version, Python 3 versions available (needs 3.11
   or newer, 3.12+ preferred), git version, Apache version and enabled modules (`proxy`,
   `proxy_http`, `headers`), the vhost file serving helppox.com on port 443, free disk on the target
   filesystem (need about 3 GB), free memory (the API uses 1.5 to 2.5 GB, the live builder up to 2 GB),
   whether systemd is used, and whether anything listens on 8600 or 8601 or already uses the URL path
   `/alibi`. If a port is taken, pick free ones and change them consistently in the unit files and the
   Apache snippet. If `/alibi` is in use, stop and ask me.
2. Create a system user `alibi` (home `/opt/alibi`, no login shell) and `/opt/alibi/` owned by it.
3. As `alibi`, create an SSH deploy key (`ssh-keygen -t ed25519 -N "" -f /opt/alibi/.ssh/id_ed25519`),
   show me the public key and wait until I say it is added to GitHub. Then add github.com to
   `known_hosts` (`ssh-keyscan github.com`) and clone the repo to `/opt/alibi/app`. If the repo has been
   made public, clone `https://github.com/apn201/Alibi.git` instead and skip the key.
4. Create a virtualenv `/opt/alibi/venv` with the newest suitable Python and install
   `requirements-service.txt`. If a pinned version does not exist for that Python, install the nearest
   available version of that package and tell me which.
5. Smoke-test as `alibi` before touching systemd or Apache: start `python -m alibi` in the background
   from `/opt/alibi/app`, wait for startup (up to a minute), then
   `curl -s http://127.0.0.1:8601/api/v1/health` and
   `curl -s -X POST -H 'Content-Type: application/json' --data @examples/event-eagle-like.json http://127.0.0.1:8601/api/v1/assessments`.
   Both must return JSON. Stop the test process.
6. Copy the unit and timer files from `deploy/` to `/etc/systemd/system/` (read each one first; they use
   `/opt/alibi/app` and `/opt/alibi/venv`), `daemon-reload`, then enable and start `alibi-api`,
   `alibi-gui`, `alibi-recorder`, `alibi-live`, `alibi-warm` (a one-off warm-up, takes a few minutes) and the timer `alibi-update.timer`. Check `systemctl status`
   for each. The recorder needs outbound HTTPS/WSS; if the firewall blocks outbound traffic, tell me
   instead of opening anything. Do not enable `alibi-copernicus.timer` yet (step 8).
7. Enable any missing Apache modules among `proxy proxy_http headers`. Put the contents of
   `deploy/apache-alibi.conf` inside the existing `<VirtualHost *:443>` block for helppox.com (or an
   included file referenced from that block). Back up every Apache file you edit, with a timestamp in
   the name. Run `apachectl configtest` (or `apache2ctl configtest`); only on "Syntax OK" reload Apache
   gracefully. If the test fails, restore the backup and tell me.
8. Copernicus login: I will log in myself. Tell me to run, on the server,
   `sudo -u alibi -H /opt/alibi/venv/bin/copernicusmarine login` and wait for my confirmation. Then run
   `systemctl start alibi-copernicus.service` once, check its result in the journal, and enable
   `alibi-copernicus.timer`. Never ask for, read or print the credentials file. Without the login the
   replay cases still work (their Copernicus data is in the repo); only the live case lacks sea state.
9. Verify: `https://helppox.com/alibi/` returns 200 and shows the console, `https://helppox.com/alibi/api/v1/health`
   returns JSON with status ok or degraded, `https://helppox.com/alibi/cases/index.json` returns JSON,
   the Swagger page `https://helppox.com/alibi/api/v1/docs` loads, and after about 15 minutes the case
   list contains `live_gof`. Check that the site's existing front page still returns what it did before.
10. Ports 8600 and 8601 must not be reachable from outside. Check the services listen on 127.0.0.1 only.

## Rules

- Do not change or restart anything unrelated to ALIBI. Graceful Apache reload only, no restart,
  unless I approve.
- Do not open firewall ports. Do not install a database. Do not touch TLS certificates.
- Never handle passwords, tokens or credentials. Where one is needed, I do it myself (steps 3 and 8).
- If a step fails twice, stop and report what you saw instead of improvising around it.

## Report back

The URLs that work, Python and package versions, files created or edited (with backup names), how to
restart (`sudo systemctl restart alibi-api alibi-gui`), logs (`journalctl -u alibi-api -u alibi-live`),
disk use of `/opt/alibi/app/data`, and how to roll back (stop and disable the units and timers, remove
the Apache snippet, reload Apache, delete `/opt/alibi` and the `alibi` user).
