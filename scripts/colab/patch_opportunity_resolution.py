"""Copy the opportunity notebook with CONFIG resolution rewritten for one TF."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def patch_notebook(src: Path, dest: Path, resolution: str) -> Path:
    """Rewrite ``CONFIG["resolution"]`` in the CONFIG cell and write ``dest``."""
    nb: Dict[str, Any] = json.loads(src.read_text(encoding="utf-8"))
    patched = False
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        source = cell.get("source", [])
        lines: List[str]
        if isinstance(source, str):
            lines = source.splitlines(keepends=True)
        else:
            lines = list(source)
        text = "".join(lines)
        if "# CELL: CONFIG" not in text.splitlines()[0:3]:
            continue
        new_lines: List[str] = []
        for line in lines:
            stripped = line.lstrip()
            if stripped.startswith('"resolution":'):
                indent = line[: len(line) - len(stripped)]
                nl = "\n" if line.endswith("\n") else ""
                new_lines.append(f'{indent}"resolution": "{resolution}",{nl}')
            else:
                new_lines.append(line)
        cell["source"] = new_lines
        patched = True
        break
    if not patched:
        raise ValueError(f"CONFIG cell not found in {src}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("src", type=Path)
    parser.add_argument("dest", type=Path)
    parser.add_argument("resolution")
    args = parser.parse_args()
    patch_notebook(args.src, args.dest, args.resolution)
    print(f"wrote {args.dest} resolution={args.resolution}")


if __name__ == "__main__":
    main()
