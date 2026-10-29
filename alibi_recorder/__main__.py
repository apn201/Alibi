"""python -m alibi_recorder [run] [--config PATH]
python -m alibi_recorder context
python -m alibi_recorder verify [DIR]
python -m alibi_recorder pull SRC [DEST]
"""

from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="alibi-recorder", description="Record the Digitraffic AIS feed to disk.")
    parser.add_argument("--config", help="TOML config file (default: $ALIBI_CONFIG or ./alibi-recorder.toml)")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("run", help="record AIS (the default)")
    sub.add_parser("context", help="record hourly snapshots of navigational warnings, winter navigation, port calls")
    v = sub.add_parser("verify", help="check closed files and report coverage")
    v.add_argument("dir", nargs="?", help="data dir (default: data_dir from config)")
    p = sub.add_parser("pull", help="copy closed hours from another recorder's data folder, checksum-verified")
    p.add_argument("src", help="source data folder (holding ais/, or the ais folder itself)")
    p.add_argument("dest", nargs="?", help="destination ais folder (default: data_dir from config)")
    p.add_argument("--label", default="umbrel", help="name for the mirrored ledger, gaps-<label>.jsonl")
    p.add_argument("--recheck", action="store_true", help="re-hash files already in dest instead of trusting .sha256")
    args = parser.parse_args(argv)

    from .config import load_config

    cfg = load_config(args.config)
    if args.cmd == "verify":
        from .verify import verify

        return verify(args.dir or cfg.data_dir)
    if args.cmd == "pull":
        from .pull import pull

        res = pull(args.src, args.dest or cfg.data_dir, label=args.label, recheck=args.recheck)
        return 1 if res.errors or res.conflicts else 0

    from datetime import datetime, timezone

    def log(msg: str) -> None:
        print(f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} {msg}", flush=True)

    if args.cmd == "context":
        from .context import ContextRecorder

        ContextRecorder(cfg.context_dir, log=log).run()
        return 0

    from .recorder import Recorder

    Recorder(cfg, log=log).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
