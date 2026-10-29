"""Turn a `# %%` percent-format script into an executed .ipynb beside it.

    python tools/run_notebook.py lab/01_first_day.py

The .py is the source (diffable); the .ipynb is output and is overwritten.
"""

import re
import sys
from pathlib import Path

import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parent.parent


def cells_from(text: str):
    for chunk in re.split(r"^# %%", text, flags=re.M)[1:]:
        header, _, body = chunk.partition("\n")
        body = body.strip("\n")
        if "[markdown]" in header:
            yield nbformat.v4.new_markdown_cell("\n".join(re.sub(r"^# ?", "", ln) for ln in body.splitlines()))
        else:
            yield nbformat.v4.new_code_cell(body)


def main(src: str) -> None:
    src = Path(src)
    nb = nbformat.v4.new_notebook()
    nb.cells = list(cells_from(src.read_text(encoding="utf-8")))
    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    NotebookClient(nb, timeout=1800, kernel_name="python3", resources={"metadata": {"path": str(ROOT)}}).execute()
    out = src.with_suffix(".ipynb")
    nbformat.write(nb, out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main(sys.argv[1])
