"""Build the v8 multi-horizon 5m research Colab (standalone, no GitHub clone).

Run from repo root::

    python scripts/colab/build_next_candle_research_notebook.py

Edits belong in the ``.py`` sources; do not hand-edit the generated ``.ipynb``.
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
OUTPUT_NOTEBOOK = COLAB_DIR / "transformer_btcusd_next_candle_research.ipynb"

INLINE_MODULE_ORDER: tuple[tuple[str, str], ...] = (
    ("## Feature contract (agent integration)", "feature_store/transformer_btcusd/contract.py"),
    ("## Derivatives features", "feature_store/transformer_btcusd/derivatives.py"),
    ("## Market structure", "feature_store/transformer_btcusd/structure.py"),
    ("## Feature engineering", "feature_store/transformer_btcusd/features.py"),
    ("## Labels / targets", "feature_store/transformer_btcusd/labels.py"),
    ("## Inference and export helpers", "feature_store/transformer_btcusd/inference.py"),
    ("## Delta Exchange India data", "scripts/colab/transformer_data.py"),
    ("## Multi-horizon model", "scripts/colab/next_candle_model.py"),
    ("## Multi-horizon research pipeline", "scripts/colab/next_candle_research.py"),
)

RESEARCH_SECTION_HEADINGS: tuple[str, ...] = (
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

INTRO_MARKDOWN = """# BTCUSD 5m multi-horizon path research (v8)

Research Colab: learn the causal relationship between historical OHLCV-derived
candle/chart structure and **how the path will behave** at 5m, 10m, 15m, 30m,
1h, and 2h. Continuous geometry is the input; named patterns are secondary.

This is **not** next-OHLC prediction, not a live agent, and not a replacement for
the production v6 all-TF trainer until a v8 5m export is validated.

Upload **this notebook only** to Google Colab. Historical OHLCV comes from the
Delta Exchange India public API. Edit repo `.py` files and regenerate:

    python scripts/colab/build_next_candle_research_notebook.py

**Colab setup:** Runtime → Change runtime type → **T4 GPU**.
"""

PIP_CELL = (
    "# Colab ships torch/pandas/numpy; install research extras.\n"
    "!pip install -q --upgrade-strategy only-if-needed "
    "pyarrow onnx onnxruntime requests scikit-learn optuna shap matplotlib seaborn\n"
)

GPU_CHECK_CELL = """import torch

print(f"PyTorch: {torch.__version__}")
if torch.cuda.is_available():
    print(f"GPU: {torch.cuda.get_device_name(0)}")
else:
    print("WARNING: No GPU detected — training will run on CPU and be much slower.")
    print("Runtime -> Change runtime type -> select a GPU (T4), then re-run this cell.")
"""

CONFIG_CELL = """from pathlib import Path
import json

CONFIG = default_research_config()
# Smoke overrides (comment out for a full research run):
# CONFIG["epochs"] = 2
# CONFIG["history_days"] = 120
# CONFIG["sequence_length"] = 64
CONFIG["run_optuna"] = False
CONFIG["run_shap"] = False
CONFIG["run_ablations"] = False
CONFIG["run_walk_forward"] = False

_content = Path("/content")
_root = _content if _content.is_dir() else Path(".")
export_dir = _root / "export" / "JackSparrow_Transformer_BTCUSD_5m"
export_dir.mkdir(parents=True, exist_ok=True)
cache_dir = _root / "cache"
cache_dir.mkdir(parents=True, exist_ok=True)
print(json.dumps(CONFIG, indent=2, default=str))
"""

SEEDS_CELL = """set_research_seed(int(CONFIG["seed"]))
print("seed", CONFIG["seed"])
"""

LOAD_CELL = """parquet = cache_dir / "btcusd_5m_raw.parquet"
refresh_data = False
if parquet.is_file() and not refresh_data:
    raw_5m = pd.read_parquet(parquet)
    print(f"Loaded cache {parquet} rows={len(raw_5m)}")
else:
    raw_5m = fetch_history_bundle(
        symbol=str(CONFIG["symbol"]),
        resolution="5m",
        history_days=int(CONFIG.get("history_days") or 900),
        base_url=str(CONFIG.get("base_url") or "https://api.india.delta.exchange"),
    )
    raw_5m.to_parquet(parquet, index=False)
    print(f"Fetched and cached {parquet} rows={len(raw_5m)}")
assert list(raw_5m.columns)
print(raw_5m.head(3))
"""

QUALITY_CELL = """quality = ohlcv_quality_report(raw_5m, "5m", symbol=str(CONFIG["symbol"]))
print(json.dumps(quality, indent=2, default=str))
"""

FEATURES_CELL = """labeled = build_labeled_frame(raw_5m, config=CONFIG)
feature_cols = [c for c in v8_feature_cols_for_resolution("5m") if c in labeled.columns]
print(f"labeled rows={len(labeled)} n_features={len(feature_cols)}")
print("chart_pattern_id in frame:", CHART_PATTERN_COL in labeled.columns)
print(labeled[feature_cols[:8]].tail(2))
"""

LEAKAGE_CELL = """leakage_audit(feature_cols)
print("Leakage audit passed: no t+1 / path / horizon target columns in X.")
"""

TARGETS_CELL = """target_cols = [
    *HORIZON_DIR_COLS,
    *HORIZON_STRUCTURE_COLS,
    *V8_CONTINUOUS_LABEL_COLS,
    VOLUME_STATE_COL,
]
present = [c for c in target_cols if c in labeled.columns]
for col in present:
    series = labeled[col].dropna()
    print(f"{col}: n={len(series)} unique={series.nunique() if series.dtype != float or series.nunique() < 20 else 'cont'}")
"""

SPLIT_CELL = """window_len = int(CONFIG["sequence_length"])
stride = int(CONFIG.get("stride") or 4)
embargo = int(
    CONFIG.get("embargo_bars")
    or CONFIG.get("path_label_horizon_bars")
    or MAX_V8_HORIZON_BARS
)
bar_slices = chronological_split(
    len(labeled),
    train_ratio=float(CONFIG["train_ratio"]),
    validation_ratio=float(CONFIG["validation_ratio"]),
    embargo=embargo,
)
print({k: (v.start, v.stop) for k, v in bar_slices.items()})
"""

SCALER_CELL = """train_df = labeled.iloc[bar_slices["train"]].reset_index(drop=True)
train_x = train_df[feature_cols].to_numpy(dtype=np.float64)
feature_finite_report(train_x, feature_cols)
scaler_mean, scaler_std = fit_train_scaler(train_x)
print("scaler fitted on TRAIN rows only", scaler_mean.shape)
per_window = str(CONFIG.get("scaler_mode") or "train_fit") == "per_window"
"""

SEQUENCES_CELL = """packed_all = windows_from_frame(
    labeled,
    feature_cols=feature_cols,
    window_len=window_len,
    stride=stride,
    scaler_mean=None if per_window else scaler_mean,
    scaler_std=None if per_window else scaler_std,
    per_window_zscore=per_window,
)
win_slices = chronological_split(
    len(packed_all["x"]),
    train_ratio=float(CONFIG["train_ratio"]),
    validation_ratio=float(CONFIG["validation_ratio"]),
    embargo=max(1, min(4, embargo // max(stride, 1))),
)
splits = split_window_dict(packed_all, win_slices)
y_mean, y_std = fit_label_stats(splits["train"]["y_path"])
print("windows", {k: len(v["x"]) for k, v in splits.items()})
"""

MODEL_CELL = """device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = NextCandleTransformer(
    n_features=len(feature_cols),
    d_model=int(CONFIG.get("d_model") or 64),
    nhead=int(CONFIG.get("nhead") or 4),
    num_layers=int(CONFIG.get("num_layers") or 2),
    dropout=float(CONFIG["dropout"]),
    max_len=window_len,
    n_continuous=len(V8_CONTINUOUS_LABEL_COLS),
).to(device)
print(model)
print("device", device)
"""

LOSS_CELL = """print("Loss lambdas (structure cannot be zeroed):")
print(json.dumps(CONFIG.get("loss_weights") or {}, indent=2))
print("Heads: 6x direction, 6x structure, 24-d path (mfe/mae/vol/trend), volume.")
"""

TRAIN_CELL = """loaders = {}
for name, shuffle in (("train", True), ("val", False), ("test", False)):
    yz, mask = standardize_labels(splits[name]["y_path"], y_mean, y_std)
    loaders[name] = make_loader(
        splits[name],
        y_path_z=yz,
        path_mask=mask,
        batch_size=int(CONFIG["batch_size"]),
        shuffle=shuffle,
        per_window_zscore=per_window,
    )
train_hist = train_next_candle(
    model,
    loaders["train"],
    loaders["val"],
    device=device,
    epochs=int(CONFIG["epochs"]),
    lr=float(CONFIG["learning_rate"]),
    weight_decay=float(CONFIG["weight_decay"]),
    patience=int(CONFIG["early_stopping_patience"]),
    loss_weights=CONFIG.get("loss_weights"),
)
print(train_hist)
if not train_hist.get("ok"):
    raise RuntimeError(f"Training aborted with non-finite loss: {train_hist}")
"""

VAL_CELL = """print("Validation:")
val_metrics = evaluate_structure_heads(model, loaders["val"], device=device)
"""

TEST_CELL = """print("Test (untouched, one run of the frozen model):")
test_metrics = evaluate_structure_heads(model, loaders["test"], device=device)
"""

WALK_CELL = """if CONFIG.get("run_walk_forward"):
    run_walk_forward_eval(
        packed_all, config=CONFIG, device=device, y_mean=y_mean, y_std=y_std
    )
else:
    n_folds = int(CONFIG.get("walk_forward_folds") or 3)
    folds = walk_forward_slices(len(packed_all["x"]), folds=n_folds, embargo=1)
    fold_spans = [(s.start, s.stop, v.start, v.stop) for s, v in folds]
    print(f"Walk-forward folds (not executed): {fold_spans}")
"""

CONFUSION_CELL = """model.eval()
xb = torch.tensor(splits["val"]["x"][:256], dtype=torch.float32, device=device)
xc = torch.tensor(splits["val"]["x_cat"][:256], dtype=torch.long, device=device)
with torch.no_grad():
    outs = model(xb, xc)
pred_dir = outs[0].argmax(dim=1).cpu().numpy()
true_dir = splits["val"]["horizon_dirs"][: len(pred_dir), 0]
print("h5m direction confusion (true x pred):")
print(confusion_counts(pred_dir, true_dir, 3))
pred_h10 = outs[1].argmax(dim=1).cpu().numpy()
true_h10 = splits["val"]["horizon_dirs"][: len(pred_h10), 1]
print("h10m direction confusion (true x pred):")
print(confusion_counts(pred_h10, true_h10, 3))
"""

CONTEXT_CELL = """pattern_context_table(labeled)
"""

SHAP_CELL = """shap_grouped_stub(feature_cols, enabled=bool(CONFIG.get("run_shap")))
"""

ABLATION_CELL = """if CONFIG.get("run_ablations"):
    groups = ablation_feature_groups("5m")
    print("Ablation direction accuracy (val, 1 epoch, out-of-sample splits):")
    for key, cols in groups.items():
        idx = np.array([feature_cols.index(c) for c in cols if c in feature_cols], dtype=np.int64)
        if len(idx) < 3:
            continue
        acc = run_ablation_epoch(
            splits["train"], splits["val"], feature_index=idx,
            config=CONFIG, device=device, y_mean=y_mean, y_std=y_std,
        )
        print(f"  {key}: {acc:.3f}  n_features={len(idx)}")
    print("If F wins only on train, call overfitting — report val/test only.")
else:
    print("Ablations skipped (CONFIG run_ablations=False). Groups A–F: OHLCV → +geometry → +trend → +structure → +chart → +HTF.")
"""

OPTUNA_CELL = """CONFIG = optuna_search_stub(CONFIG)
"""

RETRAIN_CELL = """print("Best CONFIG already trained on the research train split with val early stopping.")
print("To re-train on train+val after Optuna, concatenate those loaders and call train_next_candle again.")
print("Never peek at the final test split during search.")
"""

FINAL_TEST_CELL = """print("Final untouched test (frozen weights):")
final_test = evaluate_structure_heads(model, loaders["test"], device=device)
print(final_test)
"""

SAVE_CELL = """if not train_hist.get("ok"):
    print("Skip save: training did not succeed", train_hist)
else:
    artifact = {
        "feature_cols": list(feature_cols),
        "loss_weights": CONFIG.get("loss_weights"),
        "seed": CONFIG.get("seed"),
        "sequence_length": window_len,
        "scaler_mode": CONFIG.get("scaler_mode"),
        "feature_contract_version": FEATURE_CONTRACT_VERSION,
        "val_metrics": val_metrics,
        "test_metrics": final_test,
    }
    (export_dir / "research_run.json").write_text(
        json.dumps(artifact, indent=2, default=str), encoding="utf-8"
    )
    print("Wrote", export_dir / "research_run.json")
"""

EXPORT_CELL = """if not train_hist.get("ok"):
    print("Skip ONNX export: training did not succeed", train_hist)
else:
    onnx_path, cfg_path, meta_path = export_v8_bundle(
        model,
        export_dir,
        device=device,
        window_len=window_len,
        n_features=len(feature_cols),
        feature_cols=feature_cols,
        label_mean=y_mean,
        label_std=y_std,
        config=CONFIG,
        scaler_mean=None if per_window else scaler_mean,
        scaler_std=None if per_window else scaler_std,
    )
    print("Exported", onnx_path)
    print("feature_config", cfg_path)
    print("metadata", meta_path)
    print("Copy this directory into agent/model_storage/ after validate_transformer_bundle.py")
"""

NOTES_MARKDOWN = """## Notes

- Historical OHLCV is **immutable**. Training updates **weights only**.
- Scaler is fit on **train windows/rows only**. Optuna/walk-forward never see the final test set.
- Named candlestick class is an **input embedding**. Movement value is per-horizon
  **MFE/MAE / path_edge** at 5m through 2h.
- Production v6 all-TF notebook remains the live 15m–2h trainer until this v8
  5m export is proven.
- Agent follow-on: 15m still owns setup SL/TP; 5m timing from 5m+10m direction;
  15m–2h packets on the 5m model are telemetry only.
"""


def _inline_module_cells() -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    for heading, relative_path in INLINE_MODULE_ORDER:
        cells.append(_markdown_cell(heading))
        for chunk in _prepare_module_chunks(relative_path):
            cells.append(_code_cell(chunk))
    return cells


def _section(heading: str, source: str) -> list[dict[str, Any]]:
    return [_markdown_cell(heading), _code_cell(source)]


def build_notebook() -> dict[str, Any]:
    cells: list[dict[str, Any]] = [
        _markdown_cell(INTRO_MARKDOWN),
        *_section("## 01 Env", PIP_CELL + "\n" + GPU_CHECK_CELL),
        *_inline_module_cells(),
        *_section("## 02 CONFIG", CONFIG_CELL),
        *_section("## 03 Seeds", SEEDS_CELL),
        *_section("## 04 Load OHLCV", LOAD_CELL),
        *_section("## 05 Data quality", QUALITY_CELL),
        *_section("## 06 Causal features", FEATURES_CELL),
        *_section("## 07 Leakage audit", LEAKAGE_CELL),
        *_section("## 08 Multi-horizon path labels", TARGETS_CELL),
        *_section("## 09 Temporal split", SPLIT_CELL),
        *_section("## 10 Scaler", SCALER_CELL),
        *_section("## 11 Sequence datasets", SEQUENCES_CELL),
        *_section("## 12 Transformer", MODEL_CELL),
        *_section("## 13 Multi-task loss", LOSS_CELL),
        *_section("## 14 Train + early stopping", TRAIN_CELL),
        *_section("## 15 Validation metrics", VAL_CELL),
        *_section("## 16 Test", TEST_CELL),
        *_section("## 17 Walk-forward", WALK_CELL),
        *_section("## 18 Horizon confusion", CONFUSION_CELL),
        *_section("## 19 Pattern × context", CONTEXT_CELL),
        *_section("## 20 SHAP", SHAP_CELL),
        *_section("## 21 Ablations A–F", ABLATION_CELL),
        *_section("## 22 Optuna", OPTUNA_CELL),
        *_section("## 23 Re-train", RETRAIN_CELL),
        *_section("## 24 Final untouched test", FINAL_TEST_CELL),
        *_section("## 25 Save", SAVE_CELL),
        *_section("## 26 JackSparrow export", EXPORT_CELL),
        _markdown_cell(NOTES_MARKDOWN),
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


def _cell_text(cell: dict[str, Any]) -> str:
    return "".join(cell.get("source", []))


def validate_notebook(notebook: dict[str, Any]) -> None:
    """Ensure generated research notebook has 26 sections and no blob cells."""
    cells = notebook.get("cells", [])
    full_text = "\n".join(_cell_text(c) for c in cells)
    for pattern in FORBIDDEN_PATTERNS:
        if pattern in full_text:
            raise RuntimeError(f"Forbidden pattern in notebook: {pattern!r}")
    for heading in RESEARCH_SECTION_HEADINGS:
        if heading not in full_text:
            raise RuntimeError(f"Missing section heading: {heading!r}")
    if len(RESEARCH_SECTION_HEADINGS) != 26:
        raise RuntimeError("Expected 26 research section headings")
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
    internal_import_re = re.compile(r"^\s*from (feature_store|scripts)\.")
    for cell in cells:
        text = _cell_text(cell)
        if "export_v8_bundle(" in text and "def export_v8_bundle" not in text:
            for line in text.splitlines():
                if internal_import_re.match(line):
                    raise RuntimeError(
                        f"Train/export cell must not import internal packages: {line.strip()}"
                    )


def main() -> None:
    notebook = build_notebook()
    validate_notebook(notebook)
    OUTPUT_NOTEBOOK.write_text(
        json.dumps(notebook, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUTPUT_NOTEBOOK}")
    print(f"  cells: {len(notebook['cells'])}")
    print(f"  research sections: {len(RESEARCH_SECTION_HEADINGS)}")


if __name__ == "__main__":
    main()
