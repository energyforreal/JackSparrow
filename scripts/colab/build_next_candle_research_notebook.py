"""Build the v11 multi-TF fusion research Colab (standalone, no GitHub clone).

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
    ("## Inference helpers", "feature_store/transformer_btcusd/inference.py"),
    ("## Delta Exchange India data", "scripts/colab/transformer_data.py"),
    ("## Pattern geometry utils", "feature_store/pattern_features/pattern_utils.py"),
    ("## Native candlestick encodings", "feature_store/pattern_features/candlestick_patterns.py"),
    ("## Native chart encodings", "feature_store/pattern_features/chart_patterns.py"),
    ("## Independent MTF frames", "feature_store/transformer_btcusd/mtf_frames.py"),
    ("## Fusion 2-class labels", "feature_store/transformer_btcusd/mtf_labels.py"),
    ("## Per-TF native features", "feature_store/transformer_btcusd/mtf_features.py"),
    ("## Fused transformer", "scripts/colab/mtf_fusion_model.py"),
    ("## Fusion research pipeline", "scripts/colab/mtf_fusion_research.py"),
)

RESEARCH_SECTION_HEADINGS: tuple[str, ...] = (
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

INTRO_MARKDOWN = """# BTCUSD fused multi-TF transformer research (v11)

One shared encoder, five **independent** OHLCV streams (5m / 10m / 30m / 1h / 2h),
softmax TF fusion weights, and three 2-class heads: **+30m / +1h / +2h**.
Training labels are BEAR / BULL; the 0.5 ATR NEUTRAL dead zone is **ignored** in
cross-entropy (not a class). HOLD at live time comes from LOW grade or
``min_probability``. There are **no MFE/MAE path heads**. 5m is an input
timeframe, not a forecast head. 10m is two closed 5m bars built **outside** the
encoder — it is an input TF, not a trading head.

This notebook is the Colab trainer for the live fused bundle
(`JackSparrow_Transformer_BTCUSD_mtf_fusion`). Upload **this notebook only**,
or run it from Windows via WSL:

    powershell -File scripts/colab/run_colab_cli.ps1

Historical OHLCV comes from the Delta Exchange India public API.

Edit repo `.py` files and regenerate:

    python scripts/colab/build_next_candle_research_notebook.py

**Colab setup:** Runtime → Change runtime type → **T4 GPU**.
"""

PIP_CELL = (
    "# Colab ships torch/pandas/numpy; install research extras.\n"
    "!pip install -q --upgrade-strategy only-if-needed "
    "pyarrow onnx onnxruntime requests scikit-learn optuna shap "
    "matplotlib seaborn scipy\n"
)

GPU_CHECK_CELL = """import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch

print(f"PyTorch: {torch.__version__}")
if torch.cuda.is_available():
    print(f"GPU: {torch.cuda.get_device_name(0)}")
else:
    print("WARNING: No GPU detected — training will run on CPU and be much slower.")
    print("Runtime -> Change runtime type -> select a GPU (T4), then re-run this cell.")
"""

CONFIG_CELL = """CONFIG = default_fusion_training_config()
# Smoke overrides (comment out for a full research run):
# CONFIG["epochs"] = 2
# CONFIG["history_days"] = 120
CONFIG["run_optuna"] = False
CONFIG["run_shap"] = False
CONFIG["run_walk_forward"] = True

_content = Path("/content")
_root = _content if _content.is_dir() else Path(".")
export_dir = _root / "export" / FUSION_BUNDLE_DIR_NAME
export_dir.mkdir(parents=True, exist_ok=True)
cache_dir = _root / "cache"
cache_dir.mkdir(parents=True, exist_ok=True)
# Section 11 writes TF window memmaps under cache_dir/fusion_windows.
print(json.dumps(CONFIG, indent=2, default=str))
print("contract", FEATURE_CONTRACT_VERSION_V11)
print("input TFs", list(FUSION_INPUT_RESOLUTIONS))
print("horizons", list(FUSION_HORIZON_KEYS))
"""

SEEDS_CELL = """set_research_seed(int(CONFIG.get("seed") or 42))
print("seed", CONFIG.get("seed") or 42)
"""

LOAD_CELL = """refresh_data = False
native_tfs = ("5m", "30m", "1h", "2h")
raw_frames = {}
for res in native_tfs:
    parquet = cache_dir / f"btcusd_{res}_raw.parquet"
    if parquet.is_file() and not refresh_data:
        raw_frames[res] = pd.read_parquet(parquet)
        print(f"Loaded cache {parquet} rows={len(raw_frames[res])}")
        continue
    raw_frames[res] = fetch_history_bundle(
        symbol=str(CONFIG.get("symbol") or "BTCUSD"),
        resolution=res,
        history_days=int(CONFIG.get("history_days") or 900),
        base_url=str(CONFIG.get("base_url") or "https://api.india.delta.exchange"),
    )
    raw_frames[res].to_parquet(parquet, index=False)
    print(f"Fetched and cached {parquet} rows={len(raw_frames[res])}")

frames = fusion_frames_from_fetch(
    raw_frames["5m"], raw_frames["30m"], raw_frames["1h"], raw_frames["2h"]
)
print("fusion frames", {k: len(v) for k, v in frames.items()})
print("10m is two closed 5m bars, not a model-side resample.")
assert set(FUSION_INPUT_RESOLUTIONS) <= set(frames)
assert "15m" not in frames
"""

QUALITY_CELL = """quality = {}
for res, df in frames.items():
    quality[res] = validate_ohlcv_completeness(
        df, res, symbol=str(CONFIG.get("symbol") or "BTCUSD")
    )
    print(res, json.dumps(quality[res], indent=2, default=str))
sample_t = pd.to_datetime(frames["5m"]["time"].iloc[-2], utc=True)
assert_no_lookahead(frames["30m"], sample_t, resolution_minutes=30)
assert_no_lookahead(frames["1h"], sample_t, resolution_minutes=60)
print("as-of join uses closed bars only; sample lookahead check passed.")
"""

FEATURES_CELL = """preview = add_native_tf_features(
    frames["5m"].tail(400).reset_index(drop=True), resolution="5m"
)
feature_cols = list(fusion_feature_cols())
htf_cols = [c for c in preview.columns if str(c).startswith("htf_")]
print(f"preview rows={len(preview)} n_features={len(feature_cols)}")
print("htf_ resampled columns (must be empty):", htf_cols)
if htf_cols:
    raise RuntimeError("Fusion encodings must not resample HTF structure from 5m")
print("native TFs", list(FUSION_INPUT_RESOLUTIONS))
print(preview[feature_cols[:8]].tail(2))
"""

LEAKAGE_CELL = """leakage_audit(feature_cols)
print("Leakage audit passed: no t+1 / horizon dir / resampled HTF columns in X.")
print("last_swing_dir is a causal structure input, not a horizon target.")
"""

TARGETS_CELL = """labeled_5m = compute_fusion_horizon_labels(frames["5m"])
labeled_5m = trim_fusion_label_tail(labeled_5m)
y_preview = fusion_label_matrix(labeled_5m)
print("label rows", len(labeled_5m), "shape", y_preview.shape)
print("2-class mix BEAR/BULL plus ignore_rate (NEUTRAL) per horizon:")
print(json.dumps(label_class_mix(y_preview), indent=2))
print("dead zone is 0.5 ATR; NEUTRAL is ignore_index, not a class.")
"""

SPLIT_CELL = """window_len = int(CONFIG.get("window_len") or FUSION_WINDOW_LEN)
stride = int(CONFIG.get("stride") or 4)
embargo = int(CONFIG.get("embargo_bars") or FUSION_EMBARGO_BARS)
print("window_len", window_len, "stride", stride, "embargo", embargo)
print("Test is the final untouched tail after a purged embargo.")
"""

SCALER_CELL = """print("Scaler: per-window z-score inside collect_training_windows (zscore=True).")
print("No global scaler is fit on val or test.")
per_window = True
"""

SEQUENCES_CELL = """windows, labels, decision_times = build_dataset_from_ohlcv(
    frames,
    window_len=window_len,
    stride=stride,
    memmap_dir=cache_dir / "fusion_windows",
)
print("windows", {k: v.shape for k, v in windows.items()})
print("labels", labels.shape, "decisions", len(decision_times))
splits = purged_dev_test_split(
    windows,
    labels,
    train_frac=float(CONFIG.get("train_frac") or 0.70),
    val_frac=float(CONFIG.get("val_frac") or 0.15),
    embargo_bars=embargo,
)
print("split sizes", {k: len(v["labels"]) for k, v in splits.items()})
n_features = len(fusion_feature_cols())
feature_finite_report(splits["train"]["windows"]["5m"], feature_cols)
class_w = inverse_frequency_class_weights(
    splits["train"]["labels"], FUSION_DIRECTION_CARDINALITY
)
print("dir class weights", np.round(class_w, 3).tolist())
"""

MODEL_CELL = """device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = MtfFusionTransformer(n_features=n_features).to(device)
print(model)
print("device", device)
print("heads", list(FUSION_HORIZON_KEYS), "classes BEAR/BULL (NEUTRAL ignored)")
"""

LOSS_CELL = """print("Loss is mean cross-entropy across three 2-class horizon heads.")
print("No PnL loss. NEUTRAL labels (<0) are ignored in CE.")
print("class weights", np.round(class_w, 3).tolist())
"""

TRAIN_CELL = """train_loader = make_loader(
    splits["train"]["windows"],
    splits["train"]["labels"],
    batch_size=int(CONFIG.get("batch_size") or 64),
    shuffle=True,
)
val_loader = make_loader(
    splits["val"]["windows"],
    splits["val"]["labels"],
    batch_size=int(CONFIG.get("batch_size") or 64),
    shuffle=False,
)
test_loader = make_loader(
    splits["test"]["windows"],
    splits["test"]["labels"],
    batch_size=int(CONFIG.get("batch_size") or 64),
    shuffle=False,
)
train_hist = train_mtf_fusion(
    model,
    train_loader,
    val_loader,
    device=device,
    epochs=int(CONFIG.get("epochs") or 40),
    lr=float(CONFIG.get("lr") or 1e-4),
    weight_decay=float(CONFIG.get("weight_decay") or 1e-4),
    patience=int(CONFIG.get("early_stop_patience") or 8),
    class_weights=torch.tensor(class_w, dtype=torch.float32),
)
print(train_hist)
if not train_hist.get("ok"):
    raise RuntimeError(f"Training aborted with non-finite loss: {train_hist}")
"""

VAL_CELL = """print("Validation (used for early stopping, temperature, and grades):")
val_logits, val_y = predict_logits(model, val_loader, device)
val_metrics = {}
for j, key in enumerate(FUSION_HORIZON_KEYS):
    val_metrics[key] = horizon_metrics(val_logits[:, j, :], val_y[:, j])
    m = val_metrics[key]
    print(
        f"  {key}: acc={m['balanced_acc']:.3f} f1={m['macro_f1']:.3f} "
        f"ece={m['ece']:.3f} n={int(m['n'])}"
    )
"""

TEST_CELL = """print("Test split is frozen until section 24. Do not score it during search.")
print("test windows", {k: v.shape for k, v in splits["test"]["windows"].items()})
"""

WALK_CELL = """tf_keys = tuple(splits["train"]["windows"].keys())
n_dev = int(len(splits["train"]["labels"]) + len(splits["val"]["labels"]))
n_folds = int(CONFIG.get("walk_forward_folds") or 3)
fold_embargo = int(CONFIG.get("walk_forward_embargo") or embargo)
print("walk-forward TFs", tf_keys)
print("dev samples (train+val)", n_dev, "folds", n_folds, "embargo", fold_embargo)
print("test is excluded from walk-forward")
if CONFIG.get("run_walk_forward"):
    dev_windows = {
        res: np.concatenate(
            [splits["train"]["windows"][res], splits["val"]["windows"][res]],
            axis=0,
        )
        for res in tf_keys
    }
    dev_labels = np.concatenate(
        [splits["train"]["labels"], splits["val"]["labels"]], axis=0
    )
    walk_forward = run_walk_forward(
        dev_windows,
        dev_labels,
        n_features=n_features,
        config=CONFIG,
        device=device,
    )
    print(json.dumps(walk_forward.get("mean") or {}, indent=2, default=str))
    del dev_windows, dev_labels
else:
    folds = walk_forward_slices(n_dev, folds=n_folds, embargo=fold_embargo)
    fold_spans = [(s.start, s.stop, v.start, v.stop) for s, v in folds]
    print("Walk-forward skipped (CONFIG run_walk_forward=False). Fold plan:", fold_spans)
    walk_forward = {"folds": [], "mean": {}, "std": {}}
"""

CONFUSION_CELL = """print("Validation confusion (true x pred) per horizon, 0=BEAR 1=BULL:")
for j, key in enumerate(FUSION_HORIZON_KEYS):
    pred = val_logits[:, j, :].argmax(axis=-1)
    mat = confusion_counts(pred, val_y[:, j], FUSION_DIRECTION_CARDINALITY)
    print(key)
    print(mat)
"""

WEIGHTS_CELL = """fusion_w = model.fusion_weights().detach().cpu().numpy()
tf_keys = tuple(splits["train"]["windows"].keys())
print("softmax TF fusion weights:")
for res, w in zip(tf_keys, fusion_w):
    print(f"  {res}: {float(w):.4f}")
"""

CALIBRATION_CELL = """print("Fit one temperature per horizon on validation logits. Never uses test.")
gates = freeze_horizon_gates(val_logits, val_y, walk_forward, config=CONFIG)
for key, row in gates["horizons"].items():
    print(
        f"  {key}: T={row['temperature']:.3f} grade={row['validation_confidence']} "
        f"acc={row['balanced_acc']:.3f} ece={row['ece']:.3f}"
    )
"""

GRADES_CELL = """print("HIGH / MEDIUM may trade; LOW is telemetry-only.")
print("Each head is gated independently. Do not pick max-prob across horizons.")
print("Duration = longest accepted same-side horizon; SL/TP = ATR at that duration.")
for key, row in gates["horizons"].items():
    print(key, row["validation_confidence"], "min_p", row["min_probability"])
"""

OPTUNA_CELL = """CONFIG = optuna_search_stub(CONFIG)
"""

RETRAIN_CELL = """print("Best CONFIG was trained on the research train split with val early stopping.")
print("To re-train on train+val after Optuna, concatenate those windows and call")
print("train_mtf_fusion again. Never peek at the final test split during search.")
"""

FINAL_TEST_CELL = """print("Final untouched test (frozen weights + frozen gates):")
test_logits, test_y = predict_logits(model, test_loader, device)
final_test = {}
for j, key in enumerate(FUSION_HORIZON_KEYS):
    temp = float(gates["horizons"][key]["temperature"])
    final_test[key] = horizon_metrics(
        test_logits[:, j, :], test_y[:, j], temperature=temp
    )
    m = final_test[key]
    print(
        f"  {key}: acc={m['balanced_acc']:.3f} f1={m['macro_f1']:.3f} "
        f"ece={m['ece']:.3f} pnl={m['paper_pnl']:.3f}"
    )
promo = fusion_ready_to_promote(walk_forward, final_test, gates)
print(json.dumps(promo, indent=2, default=str))
if not promo["ready"]:
    print("DO NOT PROMOTE: no head is MEDIUM on walk-forward mean and frozen test.")
"""

SAVE_CELL = """if not train_hist.get("ok"):
    print("Skip save: training did not succeed", train_hist)
else:
    artifact = {
        "feature_cols": list(feature_cols),
        "seed": CONFIG.get("seed"),
        "window_len": window_len,
        "feature_contract_version": FEATURE_CONTRACT_VERSION_V11,
        "resolutions": list(FUSION_INPUT_RESOLUTIONS),
        "horizon_keys": list(FUSION_HORIZON_KEYS),
        "tf_fusion_weights": [float(x) for x in fusion_w],
        "val_metrics": val_metrics,
        "horizon_gates": gates,
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
    shap_grouped_stub(feature_cols, enabled=bool(CONFIG.get("run_shap")))
    onnx_path, cfg_path, meta_path = export_fusion_bundle(
        model,
        export_dir,
        n_features=n_features,
        window_len=window_len,
        config=CONFIG,
        gates=gates,
        fusion_weights=fusion_w.tolist(),
        test_metrics=final_test,
    )
    print("Exported", onnx_path)
    print("feature_config", cfg_path)
    print("metadata", meta_path)
    print("Copy this directory into agent/model_storage/ after validation.")
    import shutil
    zip_stem = export_dir.parent / FUSION_BUNDLE_DIR_NAME
    zip_path = Path(shutil.make_archive(str(zip_stem), "zip", root_dir=export_dir))
    print("Wrote zip", zip_path)
    try:
        from google.colab import files
        files.download(str(zip_path))
    except Exception as exc:
        print("Browser download skipped:", exc)
        print("Zip remains at", zip_path)
"""

NOTES_MARKDOWN = """## Notes

- Historical OHLCV is **immutable**. Training updates **weights only**.
- 10m is assembled from two closed 5m bars **outside** the model.
- Each TF runs candle/chart/structure engines on its **native** grid. No HTF resample.
- Walk-forward, Optuna, and temperature fitting never see the final test split.
- Gate each horizon independently. Duration is the longest accepted same-side head.
- SL/TP are ATR scaled to that duration (path heads were dropped).
- Promote **only** if at least one head is MEDIUM on walk-forward **mean** and
  frozen test (HIGH still needs ECE and fold std). Until then live stays on the
  current gated stack. Paper PnL is a secondary diagnostic, not the training loss.
- Section 26 zips the export folder and starts a Colab download on success.
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
        *_section("## 06 Native TF encodings", FEATURES_CELL),
        *_section("## 07 Leakage audit", LEAKAGE_CELL),
        *_section("## 08 Fusion horizon labels", TARGETS_CELL),
        *_section("## 09 Temporal split", SPLIT_CELL),
        *_section("## 10 Scaler", SCALER_CELL),
        *_section("## 11 Sequence datasets", SEQUENCES_CELL),
        *_section("## 12 Fusion transformer", MODEL_CELL),
        *_section("## 13 Cross-entropy loss", LOSS_CELL),
        *_section("## 14 Train + early stopping", TRAIN_CELL),
        *_section("## 15 Validation metrics", VAL_CELL),
        *_section("## 16 Test hold", TEST_CELL),
        *_section("## 17 Walk-forward", WALK_CELL),
        *_section("## 18 Horizon confusion", CONFUSION_CELL),
        *_section("## 19 Fusion weights", WEIGHTS_CELL),
        *_section("## 20 Temperature calibration", CALIBRATION_CELL),
        *_section("## 21 Horizon grades", GRADES_CELL),
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
        if "export_fusion_bundle(" in text and "def export_fusion_bundle" not in text:
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
