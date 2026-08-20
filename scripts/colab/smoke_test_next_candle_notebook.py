"""Validate next-candle research Colab structure (26 sections, no blobs)."""

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
    "default_research_config",
    "NextCandleTransformer",
    "compute_horizon_behavior_labels",
    "fit_train_scaler",
    "sanitize_feature_values",
    "export_v8_bundle",
    "FEATURE_CONTRACT_VERSION",
    "chart_pattern_id",
    "walk_forward_slices",
    "ablation_feature_groups",
)

RESEARCH_SECTION_HEADINGS = (
    "## 01 Env",
    "## 02 CONFIG",
    "## 03 Seeds",
    "## 04 Load OHLCV",
    "## 05 Data quality",
    "## 06 Causal features",
    "## 07 Leakage audit",
    "## 08 Multi-horizon path labels",
    "## 09 Temporal split",
    "## 10 Scaler",
    "## 11 Sequence datasets",
    "## 12 Transformer",
    "## 13 Multi-task loss",
    "## 14 Train + early stopping",
    "## 15 Validation metrics",
    "## 16 Test",
    "## 17 Walk-forward",
    "## 18 Horizon confusion",
    "## 19 Pattern × context",
    "## 20 SHAP",
    "## 21 Ablations A–F",
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
