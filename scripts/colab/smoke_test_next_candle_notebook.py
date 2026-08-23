"""Validate fused multi-TF research Colab structure (26 sections, no blobs)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

NOTEBOOK = Path(__file__).resolve().parent / "transformer_btcusd_next_candle_research.ipynb"

FORBIDDEN_PATTERNS = (
    "_PAYLOAD_B64",
    "base64.b64decode",
    "%%writefile",
    "colab_bundle",
    "import argparse",
)

REQUIRED_SYMBOLS = (
    "default_fusion_training_config",
    "MtfFusionTransformer",
    "compute_fusion_horizon_labels",
    "build_10m_ohlcv_from_5m",
    "fusion_frames_from_fetch",
    "export_fusion_bundle",
    "FEATURE_CONTRACT_VERSION_V10",
    "walk_forward_slices",
    "freeze_horizon_gates",
    "FUSION_INPUT_RESOLUTIONS",
    "precompute_featured_frames",
    "build_dataset_from_ohlcv",
)

RESEARCH_SECTION_HEADINGS = (
    "## 01 Env",
    "## 02 CONFIG",
    "## 03 Seeds",
    "## 04 Load OHLCV",
    "## 05 Data quality",
    "## 06 Native TF encodings",
    "## 07 Leakage audit",
    "## 08 Fusion horizon labels",
    "## 09 Temporal split",
    "## 10 Scaler",
    "## 11 Sequence datasets",
    "## 12 Fusion transformer",
    "## 13 Cross-entropy loss",
    "## 14 Train + early stopping",
    "## 15 Validation metrics",
    "## 16 Test hold",
    "## 17 Walk-forward",
    "## 18 Horizon confusion",
    "## 19 Fusion weights",
    "## 20 Temperature calibration",
    "## 21 Horizon grades",
    "## 22 Optuna",
    "## 23 Re-train",
    "## 24 Final untouched test",
    "## 25 Save",
    "## 26 JackSparrow export",
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

    if len(RESEARCH_SECTION_HEADINGS) != 26:
        raise AssertionError("Expected 26 research section headings")
    for heading in RESEARCH_SECTION_HEADINGS:
        if heading not in full_text:
            raise AssertionError(f"Missing section heading: {heading!r}")

    if re.search(r"^import argparse\b", full_text, re.MULTILINE):
        raise AssertionError("CLI argparse import leaked into notebook cells")
    if re.search(r"^def main\(", full_text, re.MULTILINE):
        raise AssertionError("CLI main() leaked into notebook cells")


def main() -> None:
    validate_notebook()
    print(f"OK: {NOTEBOOK.name} has 26 research sections and no forbidden patterns")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
