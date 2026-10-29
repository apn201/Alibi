"""Static server for the demo: detector/web/ at /, case files under /cases/.

Cases come from data/cases/ (built on this machine, and the live case) and from snapshot/cases/
(committed to the repo), data/ first. /cases/index.json is the union of both indexes, so a server
running from a plain git clone shows the replay cases plus its own live case.

Stdlib only. 127.0.0.1:8600 (BUILD.md ports). Case files may hold third-party data (Eagle S), so it
binds to localhost by default.
"""

from __future__ import annotations

import argparse
import functools
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "detector" / "web"
CASES = ROOT / "data" / "cases"
SNAPSHOT_CASES = ROOT / "snapshot" / "cases"


def merged_index() -> bytes:
    rows, seen = [], set()
    for d in (CASES, SNAPSHOT_CASES):
        f = d / "index.json"
        if not f.exists():
            continue
        idx = json.loads(f.read_text(encoding="utf-8"))
        for c in idx.get("cases", []) if isinstance(idx, dict) else idx:
            cid = c.get("case_id") if isinstance(c, dict) else c
            if cid not in seen and ((CASES / f"{cid}.json").exists() or (SNAPSHOT_CASES / f"{cid}.json").exists()):
                seen.add(cid)
                rows.append(c)
    return json.dumps({"cases": rows}).encode()


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
        path = path.split("?", 1)[0].split("#", 1)[0]
        if path.startswith("/cases/"):
            name = Path(path[len("/cases/"):]).name  # file name only: no directory traversal
            return str(CASES / name if (CASES / name).exists() else SNAPSHOT_CASES / name)
        return super().translate_path(path)

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/cases/index.json":
            body = merged_index()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m detector serve")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8600)
    a = ap.parse_args(argv)
    WEB.mkdir(parents=True, exist_ok=True)
    handler = functools.partial(Handler, directory=str(WEB))
    with ThreadingHTTPServer((a.host, a.port), handler) as srv:
        print(f"detector demo on http://{a.host}:{a.port}/  (web: {WEB}, cases: {CASES})")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
