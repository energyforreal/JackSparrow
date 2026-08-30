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
    "FEATURE_CONTRACT_VERSION_V11",
    "fusion_ready_to_promote",
    "walk_forward_slices",
    "freeze_horizon_gates",
    "FUSION_INPUT_RESOLUTIONS",
    "precompute_featured_frames",
    "build_dataset_from_ohlcv",
    "memmap_dir",
    "files.download",
    "run_gradient_shap",
    "shap_report",
    "optuna_search",
    "fusion_model_from_config",
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
    "## 12 Optuna",
    "## 13 Fusion transformer",
    "## 14 Cross-entropy loss",
    "## 15 Train + early stopping",
    "## 16 Validation metrics",
    "## 17 Test hold",
    "## 18 Walk-forward",
    "## 19 Horizon confusion",
    "## 20 Fusion weights",
    "## 21 Temperature calibration",
    "## 22 Horizon grades",
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

    audit = re.search(r"def leakage_audit\([\s\S]+?\n\ndef ", full_text)
    if audit is None:
        raise AssertionError("leakage_audit definition missing from notebook")
    if "endswith(\"_dir\")" in audit.group(0):
        raise AssertionError(
            "leakage_audit must not treat every *_dir column as leakage"
        )
    if "last_swing_dir" not in full_text:
        raise AssertionError("notebook should document last_swing_dir as causal")
    if "Walk-forward skipped (CONFIG run_walk_forward=False)" not in full_text:
        raise AssertionError("section 18 must skip walk-forward without concatenating windows")
    walk = re.search(
        r"tf_keys = tuple\(splits\[\"train\"\]\[\"windows\"\]\.keys\(\)\)[\s\S]+?"
        r"walk_forward = \{\"folds\": \[\], \"mean\": \{\}, \"std\": \{\}\}",
        full_text,
    )
    if walk is None:
        raise AssertionError("section 18 walk-forward cell missing robust tf_keys path")
    if "FUSION_INPUT_RESOLUTIONS" in walk.group(0):
        raise AssertionError("section 18 must not depend on FUSION_INPUT_RESOLUTIONS")

    if 'CONFIG["run_optuna"] = True' not in full_text:
        raise AssertionError("research notebook must enable run_optuna")
    search_pos = full_text.find("CONFIG = optuna_search(")
    create_pos = full_text.find("optuna.create_study")
    optimize_pos = full_text.find("study.optimize")
    train_call = full_text.find("train_hist = train_mtf_fusion(")
    if search_pos < 0 or train_call < 0 or search_pos > train_call:
        raise AssertionError("optuna_search must run before the main train call")
    if create_pos < 0 or optimize_pos < 0 or create_pos > train_call:
        raise AssertionError("optuna.create_study must appear before the main train call")
    if optimize_pos > train_call:
        raise AssertionError("study.optimize must appear before the main train call")


    # Colab inlines every module into one global namespace. Duplicate helper
    # names silently overwrite (e.g. two `_safe_atr` signatures).
    def_names = re.findall(r"^def ([A-Za-z_][A-Za-z0-9_]*)\(", full_text, re.MULTILINE)
    seen: dict[str, int] = {}
    for name in def_names:
        seen[name] = seen.get(name, 0) + 1
    dups = sorted(name for name, count in seen.items() if count > 1)
    if dups:
        raise AssertionError(
            "duplicate top-level defs would collide in Colab: " + ", ".join(dups)
        )


def main() -> None:
    validate_notebook()
    print(f"OK: {NOTEBOOK.name} has 26 research sections and no forbidden patterns")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
