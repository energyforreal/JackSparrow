"""Validate inline Colab notebook structure (no base64 / writefile / colab_bundle)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

NOTEBOOK = Path(__file__).resolve().parent / "transformer_btcusd_all_tf_train_standalone.ipynb"

FORBIDDEN_PATTERNS = (
    "_PAYLOAD_B64",
    "base64.b64decode",
    "%%writefile",
    "colab_bundle",
)

REQUIRED_SYMBOLS = (
    "FEATURE_COLS",
    "fetch_candles",
    "MarketTransformer",
    "run_all_training",
    "classify_candle_shape",
    "candle_class_ids",
    "CANDLE_CLASS_NAMES",
)

MODULE_HEADINGS = (
    "## Feature contract (agent integration)",
    "## Derivatives features",
    "## Feature engineering",
    "## Labels / targets",
    "## Inference and export helpers",
    "## Delta Exchange India data",
    "## Training pipeline",
    "## Training runner",
    "## Candle class diagnostics",
)


def _cell_text(cell: dict) -> str:
    return "".join(cell.get("source", []))


def validate_notebook(path: Path = NOTEBOOK) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Notebook not found: {path}")

    notebook = json.loads(path.read_text(encoding="utf-8"))
    cells = notebook.get("cells", [])
    full_text = "\n".join(_cell_text(c) for c in cells)

    for pattern in FORBIDDEN_PATTERNS:
        if pattern in full_text:
            raise AssertionError(f"Forbidden pattern found: {pattern!r}")

    for symbol in REQUIRED_SYMBOLS:
        if symbol not in full_text:
            raise AssertionError(f"Missing required symbol: {symbol!r}")

    for heading in MODULE_HEADINGS:
        if heading not in full_text:
            raise AssertionError(f"Missing section heading: {heading!r}")

    internal_import = re.compile(r"^\s*from (feature_store|scripts)\.", re.MULTILINE)
    for cell in cells:
        text = _cell_text(cell)
        if "run_all_training(" in text and "def run_all_training" not in text:
            matches = internal_import.findall(text)
            if matches:
                raise AssertionError("Config/train cells must not import internal packages")

    for cell in cells:
        if cell.get("cell_type") != "code":
            continue
        for line in _cell_text(cell).splitlines():
            if len(line) > 500:
                raise AssertionError(f"Line too long ({len(line)} chars); possible blob regression")

    train_idx = next(
        i
        for i, c in enumerate(cells)
        if "run_all_training(" in _cell_text(c) and "def run_all_training" not in _cell_text(c)
    )
    contract_idx = next(i for i, c in enumerate(cells) if "FEATURE_COLS" in _cell_text(c))
    if contract_idx >= train_idx:
        raise AssertionError("FEATURE_COLS must appear before train cell")

    print(f"OK: {path.name} ({len(cells)} cells)")


def main() -> None:
    try:
        validate_notebook()
    except (AssertionError, FileNotFoundError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
