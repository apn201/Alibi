"""Static server for the demo: detector/web/ at /, data/cases/*.json under /cases/.

Stdlib only. 127.0.0.1:8600 (BUILD.md ports). Case files may hold third-party data (Eagle S), so it
binds to localhost by default.
"""

from __future__ import annotations

import argparse
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "detector" / "web"
CASES = ROOT / "data" / "cases"


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
        path = path.split("?", 1)[0].split("#", 1)[0]
        if path.startswith("/cases/"):
            name = Path(path[len("/cases/"):]).name  # file name only: no directory traversal
            return str(CASES / name)
        return super().translate_path(path)

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
