"""python -m detector {cases|replay|serve|live} ..."""

import importlib
import sys


def main() -> None:
    cmds = {"cases": "detector.cases", "replay": "detector.replay", "serve": "detector.serve", "live": "detector.live"}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        sys.exit("usage: python -m detector {cases|replay|serve|live} [options]   (add -h after a command)")
    importlib.import_module(cmds[sys.argv[1]]).main(sys.argv[2:])


main()
