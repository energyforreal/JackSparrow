"""Copy the opportunity notebook with CONFIG resolution/horizon rewritten."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def patch_notebook(
    src: Path,
    dest: Path,
    resolution: str,
    horizon_bars: Optional[int] = None,
) -> Path:
    """Rewrite ``CONFIG["resolution"]`` and optionally ``horizon_bars``."""
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
            indent = line[: len(line) - len(stripped)]
            nl = "\n" if line.endswith("\n") else ""
            if stripped.startswith('"resolution":'):
                new_lines.append(f'{indent}"resolution": "{resolution}",{nl}')
            elif horizon_bars is not None and stripped.startswith('"horizon_bars":'):
                new_lines.append(f'{indent}"horizon_bars": {int(horizon_bars)},{nl}')
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
    parser.add_argument("horizon_bars", nargs="?", type=int, default=24)
    args = parser.parse_args()
    patch_notebook(args.src, args.dest, args.resolution, args.horizon_bars)
    print(
        f"wrote {args.dest} resolution={args.resolution} "
        f"horizon_bars={args.horizon_bars}"
    )


if __name__ == "__main__":
    main()
