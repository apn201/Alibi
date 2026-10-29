# Prompt for OpenClaw: deploy ALIBI to helppox.com

Copy everything below the line into OpenClaw. Before that, build the bundle on the PC
(`python tools/make_bundle.py`) and copy the resulting `dist/alibi-deploy-*.tar.gz` to the
server, for example `scp dist/alibi-deploy-*.tar.gz helppox.com:/tmp/`.

---

You are deploying a small demo web service called ALIBI to my Apache web server for the domain
helppox.com. It is a hackathon demo that must be reachable at https://helppox.com/alibi/ by
Friday 2026-10-30 12:00 Finnish time. Work carefully: this server hosts other sites, and none of
them may break.

## What ALIBI is

- A Python API (FastAPI + uvicorn) that runs as its own process on 127.0.0.1:8601. Start command,
  from the app directory: `python -m alibi`. Health check: `GET http://127.0.0.1:8601/api/v1/health`.
- A static web GUI in `detector/web/` and static JSON replay cases in `data/cases/`.
- Apache serves the GUI and cases and reverse-proxies `/alibi/api/` to the API. Apache keeps HTTPS.

## Input

A deploy bundle `alibi-deploy-<timestamp>.tar.gz` in `/tmp/` (code plus about 0.5–1 GB of data).
If you cannot find it, stop and ask me; do not try to fetch it from anywhere else.

The bundle contains, among others: `requirements-service.txt` (pinned Python packages),
`deploy/alibi-api.service` (systemd unit), `deploy/apache-alibi.conf` (the Apache snippet).
Read both deploy files before you use them.

## Steps

1. Look before you change anything. Report: OS and version, Python 3 versions available (the
   app needs Python 3.11 or newer; 3.12+ preferred), Apache version, which modules are enabled
   (`proxy`, `proxy_http`, `headers`, `alias`), the vhost file that serves helppox.com on port 443,
   free disk space on the target filesystem (need about 3 GB), free memory (the API uses about
   1.5–2.5 GB of RAM), and whether anything already listens on port 8601 or already uses the URL
   path `/alibi`. If port 8601 is taken, pick a free port and use it consistently in the unit and
   the Apache snippet. If `/alibi` is already used, stop and ask me.
2. Create a system user `alibi` with no login shell, and `/opt/alibi/` owned by it.
3. Unpack the bundle into `/opt/alibi/app/`. Create a virtualenv in `/opt/alibi/venv/` with the
   newest suitable Python and install `requirements-service.txt`. If a pinned version does not
   exist for that Python, install the nearest available version of that package and tell me which.
4. Smoke-test as the `alibi` user before touching Apache:
   `cd /opt/alibi/app && /opt/alibi/venv/bin/python -m alibi` in the background, wait for startup
   (it loads data for up to a minute), then `curl -s http://127.0.0.1:8601/api/v1/health` and
   `curl -s -X POST -H 'Content-Type: application/json' --data @examples/event-eagle-like.json http://127.0.0.1:8601/api/v1/assessments`.
   Both must return JSON. Stop the test process.
5. Install `deploy/alibi-api.service` as `/etc/systemd/system/alibi-api.service`, `daemon-reload`,
   enable and start it, and check `systemctl status` and the health URL again. If the server does not
   use systemd, use its own service manager and tell me.
6. Enable any missing Apache modules among `proxy proxy_http headers alias`. Put the contents of
   `deploy/apache-alibi.conf` inside the existing `<VirtualHost *:443>` block for helppox.com
   (or as an included file referenced from that block). Keep a backup copy of every Apache file you
   edit, with a timestamp in the name. Run `apachectl configtest` (or `apache2ctl configtest`). Only
   if it says Syntax OK, reload Apache gracefully. If the test fails, restore the backup and tell me.
7. Verify from the server: `curl -sI https://helppox.com/alibi/` returns 200,
   `curl -s https://helppox.com/alibi/api/v1/health` returns JSON with status ok or degraded,
   `curl -s https://helppox.com/alibi/cases/index.json` returns JSON, and the Swagger page
   `https://helppox.com/alibi/api/v1/docs` loads. Also check that the site's existing front page
   still returns what it returned before you started.
8. Firewall: port 8601 must not be reachable from outside. Check that the service listens on
   127.0.0.1 only.

## Rules

- Do not change or restart anything unrelated to ALIBI. Graceful Apache reload only, no restart,
  unless I approve.
- Do not open new firewall ports. Do not install a database. Do not touch TLS certificates.
- No secrets are needed. If anything asks for a password, token or credential, stop and ask me.
- If a step fails twice, stop and report what you saw instead of improvising around it.

## Report back

The URLs that work, the Python and package versions installed, the files you created or edited
(with backup names), how to restart the service (`sudo systemctl restart alibi-api`), where the logs
are (`journalctl -u alibi-api`), and how to roll back (stop and disable the unit, remove the
Apache snippet, reload Apache, delete `/opt/alibi`).

## Updating later

A new bundle replaces `/opt/alibi/app` except `data/alibi-ledger.sqlite` (the audit ledger); keep
that file, unpack the rest, `pip install -r requirements-service.txt`, restart the unit, run the
checks in step 7.
