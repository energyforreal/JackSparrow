"""Build the CPU-only v15 fusion diagnostics Colab.

Run from repo root::

    python scripts/colab/build_fusion_diagnostics_notebook.py

Do not hand-edit the generated ``.ipynb``. This notebook must not train
``MtfFusionTransformer``.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.colab.build_standalone_notebook import (
    FORBIDDEN_PATTERNS,
    MAX_LINE_LENGTH,
    _code_cell,
    _markdown_cell,
    _prepare_module_chunks,
)

COLAB_DIR = Path(__file__).resolve().parent
OUTPUT_NOTEBOOK = COLAB_DIR / "transformer_btcusd_fusion_diagnostics.ipynb"

INLINE_MODULE_ORDER: tuple[tuple[str, str], ...] = (
    ("## Feature contract", "feature_store/transformer_btcusd/contract.py"),
    ("## Derivatives features", "feature_store/transformer_btcusd/derivatives.py"),
    ("## Market structure", "feature_store/transformer_btcusd/structure.py"),
    ("## Feature engineering", "feature_store/transformer_btcusd/features.py"),
    ("## Inference helpers", "feature_store/transformer_btcusd/inference.py"),
    ("## Delta Exchange India data", "scripts/colab/transformer_data.py"),
    ("## Pattern geometry utils", "feature_store/pattern_features/pattern_utils.py"),
    ("## Native candlestick encodings", "feature_store/pattern_features/candlestick_patterns.py"),
    ("## Native chart encodings", "feature_store/pattern_features/chart_patterns.py"),
    ("## Independent MTF frames", "feature_store/transformer_btcusd/mtf_frames.py"),
    ("## Fusion 2-class labels", "feature_store/transformer_btcusd/mtf_labels.py"),
    ("## Label V2 path targets", "feature_store/transformer_btcusd/mtf_labels_v2.py"),
    ("## Per-TF native features", "feature_store/transformer_btcusd/mtf_features.py"),
    ("## Fusion diagnostics", "scripts/colab/fusion_diagnostics.py"),
    ("## Direction predictability", "scripts/colab/direction_predictability.py"),
    ("## Path-edge regression", "scripts/colab/path_regression.py"),
)

SECTION_HEADINGS: tuple[str, ...] = (
    "## 01 Env",
    "## 02 Load OHLCV",
    "## 03 Run diagnostics",
    "## 04 Branch",
)

TRAIN_FORBIDDEN: tuple[str, ...] = (
    "train_mtf_fusion(",
    "fusion_model_from_config(",
    "export_fusion_bundle(",
    "optuna_search(",
    "class MtfFusionTransformer",
)

INTRO_MARKDOWN = """# BTCUSD v15 fusion diagnostics (no training)

CPU-only. This notebook answers whether Label V2 direction heads
(10m / 15m / 30m / 1h) fail because of labels, leakage, or a market state
that does not determine the frozen-theta class. Last-bar direction
predictability (confusion, AUC, log-loss vs prior, knockout) runs on CPU
here. Checkpoint ``best.pt`` confusion is CLI-only. **Do not** train
`MtfFusionTransformer` here. Live remains v11. Do not copy anything into
`agent/model_storage/`. 2h stays an encoder input, not a research label.

Uses cached Delta India OHLCV when present (`/content/cache/btcusd_5m_raw.parquet`).

Edit repo `.py` files and regenerate:

    python scripts/colab/build_fusion_diagnostics_notebook.py

**Colab setup:** Runtime → CPU is enough.
"""

PIP_CELL = (
    "# Diagnostics need sklearn/pandas; no GPU training extras.\n"
    "!pip install -q --upgrade-strategy only-if-needed "
    "pyarrow requests scikit-learn scipy\n"
)

ENV_CELL = """import json
from pathlib import Path

import numpy as np
import pandas as pd

print("numpy", np.__version__)
print("CPU diagnostics; Transformer training is out of scope.")
"""

LOAD_CELL = """from datetime import datetime, timedelta, timezone

cache_dir = Path("/content/cache")
cache_dir.mkdir(parents=True, exist_ok=True)
parquet_5m = cache_dir / "btcusd_5m_raw.parquet"
cfg = default_fusion_training_config()
history_days = int(cfg.get("history_days") or 900)
base_url = str(cfg.get("base_url") or "https://api.india.delta.exchange")

if parquet_5m.is_file():
    df5m = pd.read_parquet(parquet_5m)
    print(f"Loaded cache {parquet_5m} rows={len(df5m)}")
else:
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=history_days)
    print(f"Fetching BTCUSD 5m for {history_days}d...")
    df5m = fetch_candles(
        "BTCUSD",
        "5m",
        int(start_dt.timestamp()),
        int(end_dt.timestamp()),
        base_url,
    )
    quality = validate_ohlcv_completeness(df5m, "5m", symbol="BTCUSD")
    print("5m", json.dumps(quality, indent=2, default=str))
    df5m.to_parquet(parquet_5m, index=False)

frames = {"5m": df5m}
for res in ("30m", "1h", "2h"):
    path = cache_dir / f"btcusd_{res}_raw.parquet"
    if path.is_file():
        frames[res] = pd.read_parquet(path)
        print(f"Loaded cache {path} rows={len(frames[res])}")
if all(k in frames for k in ("30m", "1h", "2h")):
    frames = fusion_frames_from_fetch(
        frames["5m"], frames["30m"], frames["1h"], frames["2h"]
    )
print("frames", {k: len(v) for k, v in frames.items()})
"""

RUN_CELL = """score_test = True
ablate_groups = True
path_regression = False
report = run_fusion_diagnostics(
    df5m,
    frames=frames,
    score_test=score_test,
    ablate_groups=ablate_groups,
    score_path_regression=path_regression,
)
out_dir = Path("/content/export/fusion_diagnostics")
out_dir.mkdir(parents=True, exist_ok=True)
out_path = out_dir / "report.json"
out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
print("wrote", out_path)
print("d1_ok", report.get("d1_index_audit", {}).get("ok"))
print("d2_ok", report.get("d2_intervals", {}).get("ok"))
print("d9_ok", report.get("d9_truncation", {}).get("ok"))
print("branch", report.get("branch"), "(diagnostics token, not the bake-off)")
dp = report.get("direction_predictability") or {}
for key, horizon in (dp.get("horizons") or {}).items():
    print(
        key,
        "discovery",
        horizon.get("discovery_reading"),
        "confirmatory",
        horizon.get("confirmatory_reading"),
    )
pr = report.get("path_regression") or {}
for key, horizon in (pr.get("horizons") or {}).items():
    print(
        "path",
        key,
        horizon.get("discovery_reading"),
        horizon.get("confirmatory_reading"),
    )
"""

BRANCH_CELL = """print(json.dumps({
    "branch": report.get("branch"),
    "notes": report.get("notes"),
    "expectancy_minus_cost": report.get("expectancy_minus_cost"),
}, indent=2, default=str))
print(
    "Pre-registered readings live under direction_predictability. "
    "decide_branch is a diagnostics token, not the experiment verdict. "
    "Checkpoint confusion is CLI-only (best.pt)."
)
"""


def _cell_text(cell: dict[str, Any]) -> str:
    return "".join(cell.get("source", []))


def _section(heading: str, source: str) -> list[dict[str, Any]]:
    return [_markdown_cell(heading), _code_cell(source)]


def _inline_module_cells() -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    for heading, relative_path in INLINE_MODULE_ORDER:
        cells.append(_markdown_cell(heading))
        for chunk in _prepare_module_chunks(relative_path):
            cells.append(_code_cell(chunk))
    return cells


def build_notebook() -> dict[str, Any]:
    cells: list[dict[str, Any]] = [
        _markdown_cell(INTRO_MARKDOWN),
        *_section("## 01 Env", PIP_CELL + "\n" + ENV_CELL),
        *_inline_module_cells(),
        *_section("## 02 Load OHLCV", LOAD_CELL),
        *_section("## 03 Run diagnostics", RUN_CELL),
        *_section("## 04 Branch", BRANCH_CELL),
    ]
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {
                "name": "python",
                "pygments_lexer": "ipython3",
            },
            "colab": {"provenance": []},
        },
        "cells": cells,
    }


def validate_notebook(notebook: dict[str, Any]) -> None:
    """CPU diagnostics notebook: four sections, no training, no CLI main."""
    cells = notebook.get("cells", [])
    full_text = "\n".join(_cell_text(c) for c in cells)
    for pattern in FORBIDDEN_PATTERNS:
        if pattern in full_text:
            raise RuntimeError(f"Forbidden pattern in notebook: {pattern!r}")
    for token in TRAIN_FORBIDDEN:
        if token in full_text:
            raise RuntimeError(f"Training token leaked into diagnostics notebook: {token}")
    for heading in SECTION_HEADINGS:
        if heading not in full_text:
            raise RuntimeError(f"Missing section heading: {heading!r}")
    for cell in cells:
        if cell.get("cell_type") != "code":
            continue
        for line in _cell_text(cell).splitlines():
            if len(line) > MAX_LINE_LENGTH:
                raise RuntimeError(
                    f"Line exceeds {MAX_LINE_LENGTH} chars: {line[:80]}..."
                )
    if re.search(r"^import argparse\b", full_text, re.MULTILINE):
        raise RuntimeError("CLI argparse import leaked into notebook cells")
    if re.search(r"^def main\(", full_text, re.MULTILINE):
        raise RuntimeError("CLI main() leaked into notebook cells")


def main() -> None:
    notebook = build_notebook()
    validate_notebook(notebook)
    OUTPUT_NOTEBOOK.write_text(
        json.dumps(notebook, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUTPUT_NOTEBOOK}")
    print(f"  cells: {len(notebook['cells'])}")
    print(f"  diagnostic sections: {len(SECTION_HEADINGS)}")


if __name__ == "__main__":
    main()
