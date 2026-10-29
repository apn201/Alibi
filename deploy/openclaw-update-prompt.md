# Prompt for OpenClaw: update ALIBI on helppox.com (2026-10-29 evening)

Copy everything below the line into OpenClaw.

---

ALIBI is already deployed on this server under /opt/alibi (user `alibi`, repo clone in /opt/alibi/app,
virtualenv /opt/alibi/venv, systemd units alibi-api, alibi-gui, alibi-recorder, alibi-live, alibi-warm,
alibi-update(.timer), alibi-copernicus(.timer)). https://helppox.com/alibi/ works. Bring it up to date.
Work carefully; nothing else on the server may change.

Background: `alibi-update.service` fails with status 203/EXEC because the unit called `/usr/bin/runuser`,
and on Rocky Linux `runuser` is `/usr/sbin/runuser`. The fixed unit is in the repo. The repo
(github.com/apn201/Alibi) is now public, so `git pull` works over HTTPS without a key; an existing SSH
remote with the deploy key also keeps working, leave it as it is.

1. Look first: `git -C /opt/alibi/app status --short` and `git -C /opt/alibi/app log --oneline -1` as user
   alibi. If there are local changes to tracked files, show them to me and stop. Untracked files under
   data/ are expected (git ignores data/).
2. If you earlier created a symlink for `vessel_keys.parquet` under /opt/alibi/app/data/derived/profile_db/,
   remove that symlink only (the code now falls back to snapshot/ itself). Check first that it is a symlink
   (`test -L`), and do not delete any regular file or directory.
3. Pull as alibi: `sudo -u alibi git -C /opt/alibi/app pull --ff-only`. It must fast-forward; if not, stop
   and tell me.
4. `sudo -u alibi /opt/alibi/venv/bin/pip install -q -r /opt/alibi/app/requirements-service.txt`.
5. Re-install the unit files that changed: compare each file in /opt/alibi/app/deploy/*.service and
   *.timer with /etc/systemd/system/ (`diff`). Copy the changed ones (at least alibi-update.service, and
   alibi-warm.service if it is not installed yet), then `systemctl daemon-reload`.
6. Run the update once: `systemctl start alibi-update.service`, then `systemctl status alibi-update.service`
   must show it finished successfully (oneshot, status=0). It restarts alibi-api, alibi-gui and alibi-live
   and starts alibi-warm in the background.
7. If the Copernicus login was done (the file /opt/alibi/.copernicusmarine/.copernicusmarine-credentials
   exists; do not open or print it), make sure `alibi-copernicus.timer` is enabled and run
   `systemctl start alibi-copernicus.service` once; report its last 20 journal lines.
8. Check after about 5 minutes:
   - `curl -s https://helppox.com/alibi/api/v1/health` returns status ok;
   - `curl -s https://helppox.com/alibi/cases/index.json` lists `live_gof` and the replay cases;
   - this link loads and, after 20-60 s, shows "TOP BAND 53 -> 49 WITH SEA STATE ON":
     https://helppox.com/alibi/#case=fi_fleet_2026_10_05&src=profile,own_habit,place,fleet,notices,position_quality,identity,ice&then=sea_state
   - `systemctl status alibi-warm` shows it ran (it takes a few minutes);
   - `systemctl list-timers 'alibi-*'` shows alibi-update and alibi-copernicus.
9. Report: the commit now deployed, which unit files you replaced, the result of each check, and anything
   that failed with its journal lines (`journalctl -u <unit> -n 30`).

Rules: graceful only, no Apache changes are needed for this update, do not touch other services or
sites, do not open ports, never read or print credentials. If a step fails twice, stop and report.
