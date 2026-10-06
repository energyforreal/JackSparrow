"""Build the v15 Label V2 multi-TF fusion research Colab (standalone, no GitHub clone).

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
    ("## Label V2 path targets (research only)", "feature_store/transformer_btcusd/mtf_labels_v2.py"),
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

INTRO_MARKDOWN = """# BTCUSD fused multi-TF transformer research (v15 Label V2)

One shared encoder, five **independent** OHLCV streams (5m / 10m / 30m / 1h / 2h),
softmax TF fusion weights, four **3-class** direction heads (**+10m / +15m / +30m / +1h**)
plus per-horizon **return / long-short MFE/MAE** path heads. NEUTRAL is a trained class
(frozen theta **0.50 ATR** on all four heads). Persistence
and TP/SL path diagnostics stay off the loss. 5m is an input timeframe, not a forecast
head. 10m is two closed 5m bars built **outside** the encoder. **2h stays an encoder
input**; it is not a research label head.

This notebook trains a **research-only** v15 bundle
(`JackSparrow_Transformer_BTCUSD_mtf_fusion_v15`). **Do not** copy it into
`agent/model_storage/`. Live remains v11 2-class ONNX loaded by FusionModelNode.
v12/v13/v14/v15 research contracts must not load in FusionModelNode.
`fusion_ready_to_promote` is always `ready=false` (`research_v15_not_live`).

This pass is **later_direction_only**: path SmoothL1 weights are 0 and class
weights are off (uniform CE). Path heads stay on the ONNX graph but are not
trained. Judge balanced accuracy against last-bar D7 (~0.36–0.38), not 50%.

v14 inputs drop duplicate scales and pattern flags, keep ATR-unit geometry,
channel-scale (not full-window z-score), and embed `candle_class_id` plus
`chart_pattern_id`. `FEATURE_CONTRACT_VERSION_V15` names the four-head ONNX
layout this research trainer emits.

Optuna stays **off** (`run_optuna=False`) so the main train uses the hand
defaults (lr / dropout / weight_decay). Set it true to search those on val
loss **before** the main train. Historical OHLCV comes from the Delta Exchange
India public API.

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
CONFIG["epochs"] = 40
CONFIG["early_stop_patience"] = 8
CONFIG["batch_size"] = 128
CONFIG["lr_schedule"] = "plateau"
CONFIG["run_optuna"] = False
CONFIG["optuna_trials"] = 3
CONFIG["optuna_trial_epochs"] = 4
CONFIG["optuna_refresh"] = False
CONFIG["run_shap"] = False
CONFIG["shap_background"] = 32
CONFIG["shap_explain_n"] = 64
CONFIG["amp"] = True
CONFIG["dataloader_workers"] = 2
CONFIG["prefetch_factor"] = 4
CONFIG["pin_memory"] = True
CONFIG["run_walk_forward"] = True
# Reuse cache/optuna_best.json unless optuna_refresh=True.
# Weights-only retrain: CONFIG["run_walk_forward"] = False.

_content = Path("/content")
_root = _content if _content.is_dir() else Path(".")
export_dir = _root / "export" / FUSION_V15_BUNDLE_DIR_NAME
export_dir.mkdir(parents=True, exist_ok=True)
cache_dir = _root / "cache"
cache_dir.mkdir(parents=True, exist_ok=True)
# Section 11 writes TF window memmaps under cache_dir/fusion_windows.
print(json.dumps(CONFIG, indent=2, default=str))
print("contract", FEATURE_CONTRACT_VERSION_V15)
print("experiment", CONFIG.get("experiment"), "use_class_weights", CONFIG.get("use_class_weights"))
print("path_loss_weights", CONFIG.get("path_loss_weights"))
print("label scheme", CONFIG.get("label_scheme"), "theta", CONFIG.get("label_v2_theta"))
print("input TFs", list(FUSION_INPUT_RESOLUTIONS))
print("horizons", list(LABEL_V2_HORIZON_KEYS))
print("fusion window spans (target", FUSION_TARGET_WINDOW_MINUTES, "min):")
for res, width in fusion_window_lens().items():
    minutes = RESOLUTION_MINUTES[res]
    span = int(width) * int(minutes)
    print(f"  {res:4}  bars={width:4}  span_min={span}  err={span - FUSION_TARGET_WINDOW_MINUTES}")
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
feature_cols = list(fusion_feature_cols_v14())
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
v2_leak = set(label_v2_future_leak_cols())
overlap = sorted(set(feature_cols) & v2_leak)
print("Label V2 path cols are leak-only; overlap with X:", overlap)
if overlap:
    raise RuntimeError(f"Label V2 targets leaked into features: {overlap}")
"""

TARGETS_CELL = """labeled_5m = compute_fusion_path_targets(frames["5m"])
labeled_5m = trim_label_v2_tail(labeled_5m)
y_dir_preview, y_reg_preview = fusion_label_v2_matrices(labeled_5m)
print("label rows", len(labeled_5m), "dir", y_dir_preview.shape, "path", y_reg_preview.shape)
print("3-class mix BEAR/NEUTRAL/BULL (NEUTRAL is trained) per horizon:")
print(json.dumps(label_v2_class_mix(y_dir_preview), indent=2))
print("frozen theta", json.dumps(dict(LABEL_V2_THETA_FROZEN), indent=2))
print("path fields", list(LABEL_V2_REG_FIELDS), "invalid dir code is -1")

print("Label V2 distribution gate (diagnostics; training y is the matrices above):")
v2_report = summarize_label_v2(frames["5m"])
print(format_label_v2_table(v2_report))
print("overall", v2_report.get("overall"))
print("Training uses fusion_label_v2_matrices; persist/TP-SL stay off the loss.")
"""

SPLIT_CELL = """window_lens = dict(CONFIG.get("window_lens") or fusion_window_lens())
window_len = int(CONFIG.get("window_len") or window_lens["5m"] or FUSION_WINDOW_LEN)
stride = int(CONFIG.get("stride") or 4)
embargo = int(CONFIG.get("embargo_bars") or FUSION_EMBARGO_BARS)
print("window_lens", window_lens)
print("window_len (5m warm-up)", window_len, "stride", stride, "embargo", embargo)
print("Test is the final untouched tail after a purged embargo.")
"""

SCALER_CELL = """print("Scaler: v14 channel scale inside collect_training_windows_v14.")
print("ret_1 is per-window z-scored; ATR ratios and RSI/ADX keep level.")
print("No global scaler is fit on val or test.")
per_window = False
"""

SEQUENCES_CELL = """built = build_dataset_from_ohlcv(
    frames,
    window_lens=window_lens,
    window_len=window_len,
    stride=stride,
    memmap_dir=cache_dir / "fusion_windows",
)
windows = built.windows
labels = built.labels
decision_times = built.decision_times
candle_ids = built.candle_ids
chart_ids = built.chart_ids
print("windows", {k: v.shape for k, v in windows.items()})
print("labels dir", labels.direction.shape, "path", labels.path.shape, "decisions", len(decision_times))
splits = purged_dev_test_split(
    windows,
    labels,
    train_frac=float(CONFIG.get("train_frac") or 0.70),
    val_frac=float(CONFIG.get("val_frac") or 0.15),
    embargo_bars=embargo,
    candle_ids=candle_ids,
    chart_ids=chart_ids,
)
print("split sizes", {k: len(v["labels"]) for k, v in splits.items()})
n_features = len(fusion_feature_cols_v14())
feature_finite_report(splits["train"]["windows"]["5m"], feature_cols)
if CONFIG.get("use_class_weights", True):
    class_w = inverse_frequency_class_weights(
        splits["train"]["labels"], LABEL_V2_DIRECTION_CARDINALITY
    )
    class_w_t = torch.tensor(class_w, dtype=torch.float32)
    print("dir class weights", np.round(class_w, 3).tolist())
else:
    class_w = None
    class_w_t = None
    print("dir class weights off (uniform CE)")
"""

MODEL_CELL = """device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = fusion_model_from_config(n_features, CONFIG).to(device)
print(model)
print("device", device)
print("dropout", CONFIG.get("dropout"), "lr", CONFIG.get("lr"))
print("heads", list(LABEL_V2_HORIZON_KEYS), "classes BEAR/NEUTRAL/BULL; path heads exported, not trained")
"""

LOSS_CELL = """print("Loss is 3-class CE (NEUTRAL trained). Path SmoothL1 is off when path weights are 0.")
print("horizon_loss_weights", CONFIG.get("horizon_loss_weights"))
print("path_loss_weights", CONFIG.get("path_loss_weights"))
print("use_class_weights", CONFIG.get("use_class_weights"))
print("experiment", CONFIG.get("experiment"))
print("label_smoothing", CONFIG.get("label_smoothing"))
print("No PnL loss. Invalid dirs (<0) and non-finite path values are masked.")
print("class weights", None if class_w is None else np.round(class_w, 3).tolist())
"""

TRAIN_CELL = """train_hist = train_mtf_fusion(
    model,
    train_loader,
    val_loader,
    device=device,
    epochs=int(CONFIG.get("epochs") or 40),
    lr=float(CONFIG.get("lr") or 1e-4),
    weight_decay=float(CONFIG.get("weight_decay") or 1e-3),
    patience=int(CONFIG.get("early_stop_patience") or 8),
    class_weights=class_w_t,
    label_smoothing=float(CONFIG.get("label_smoothing") or 0.0),
    horizon_weights=list(CONFIG.get("horizon_loss_weights") or [1.0, 1.0, 1.0, 1.0]),
    lr_schedule=str(CONFIG.get("lr_schedule") or "plateau"),
    amp=bool(CONFIG.get("amp", True)),
    path_task_weights=dict(
        CONFIG.get("path_loss_weights") or LABEL_V2_DIRECTION_ONLY_PATH_LOSS_WEIGHTS
    ),
)
print(train_hist)
if not train_hist.get("ok"):
    raise RuntimeError(f"Training aborted with non-finite loss: {train_hist}")
"""

VAL_CELL = """print("Validation (used for early stopping, temperature, and grades):")
val_logits, val_y = predict_logits(model, val_loader, device)
val_metrics = {}
for j, key in enumerate(LABEL_V2_HORIZON_KEYS):
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

WALK_CELL = """tf_keys = tuple(windows.keys())
n_folds = int(CONFIG.get("walk_forward_folds") or 3)
fold_embargo = int(CONFIG.get("walk_forward_embargo") or embargo)
print("walk-forward TFs", tf_keys)
print("test is excluded; folds use the contiguous prefix through val")
if CONFIG.get("run_walk_forward"):
    dev_windows, dev_labels = development_prefix(
        windows,
        labels,
        train_frac=float(CONFIG.get("train_frac") or 0.70),
        val_frac=float(CONFIG.get("val_frac") or 0.15),
    )
    print(
        "dev samples (contiguous through val)",
        len(dev_labels),
        "folds",
        n_folds,
        "embargo",
        fold_embargo,
    )
    walk_forward = run_walk_forward(
        dev_windows,
        dev_labels,
        n_features=n_features,
        config=CONFIG,
        device=device,
        candle_ids=slice_id_windows(candle_ids, slice(0, len(dev_labels))),
        chart_ids=slice_id_windows(chart_ids, slice(0, len(dev_labels))),
    )
    print(json.dumps(walk_forward.get("mean") or {}, indent=2, default=str))
    del dev_windows, dev_labels
else:
    n_dev = int(len(splits["train"]["labels"]) + len(splits["val"]["labels"]))
    folds = walk_forward_slices(n_dev, folds=n_folds, embargo=fold_embargo)
    fold_spans = [(s.start, s.stop, v.start, v.stop) for s, v in folds]
    print("Walk-forward skipped (CONFIG run_walk_forward=False). Fold plan:", fold_spans)
    walk_forward = {"folds": [], "mean": {}, "std": {}}
"""

CONFUSION_CELL = """print("Validation confusion (true x pred) per horizon, 0=BEAR 1=NEUTRAL 2=BULL:")
for j, key in enumerate(LABEL_V2_HORIZON_KEYS):
    pred = val_logits[:, j, :].argmax(axis=-1)
    mat = confusion_counts(pred, val_y[:, j], LABEL_V2_DIRECTION_CARDINALITY)
    print(key)
    print(mat)
"""

WEIGHTS_CELL = """fusion_w = tensor_to_numpy(model.fusion_weights())
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

OPTUNA_CELL = """device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
_loader_kw = _loader_runtime_kwargs(CONFIG, device)
_eval_kw = dict(_loader_kw)
_eval_kw["windows_in_ram"] = False
train_loader = make_loader(
    splits["train"]["windows"],
    splits["train"]["labels"],
    batch_size=int(CONFIG.get("batch_size") or 128),
    shuffle=True,
    candle_ids=splits["train"].get("candle_ids"),
    chart_ids=splits["train"].get("chart_ids"),
    **_loader_kw,
)
val_loader = make_loader(
    splits["val"]["windows"],
    splits["val"]["labels"],
    batch_size=int(CONFIG.get("batch_size") or 128),
    shuffle=False,
    candle_ids=splits["val"].get("candle_ids"),
    chart_ids=splits["val"].get("chart_ids"),
    **_eval_kw,
)
test_loader = make_loader(
    splits["test"]["windows"],
    splits["test"]["labels"],
    batch_size=int(CONFIG.get("batch_size") or 128),
    shuffle=False,
    candle_ids=splits["test"].get("candle_ids"),
    chart_ids=splits["test"].get("chart_ids"),
    **_eval_kw,
)
print("Loaders ready. Test is frozen until the final test section.")
print("loader", json.dumps(_loader_kw, indent=2, default=str))
print("AMP", bool(CONFIG.get("amp")) and device.type == "cuda", "device", device)
CONFIG = optuna_search(
    CONFIG,
    n_features=n_features,
    train_loader=train_loader,
    val_loader=val_loader,
    device=device,
    class_weights=class_w_t,
    cache_dir=cache_dir,
)
print(
    "post-optuna",
    json.dumps(
        {
            "lr": CONFIG.get("lr"),
            "dropout": CONFIG.get("dropout"),
            "weight_decay": CONFIG.get("weight_decay"),
            "optuna_best": CONFIG.get("optuna_best"),
        },
        indent=2,
        default=str,
    ),
)
"""

RETRAIN_CELL = """print("Main train already uses Optuna winners when run_optuna=True.")
print("No second fit on train+val. Test split stays frozen.")
"""

FINAL_TEST_CELL = """print("Final untouched test (frozen weights + frozen gates):")
test_logits, test_y = predict_logits(model, test_loader, device)
final_test = {}
for j, key in enumerate(LABEL_V2_HORIZON_KEYS):
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
    print(
        "DO NOT PROMOTE: v15 Label V2 research export is not live-compatible "
        f"({promo.get('reason')}). Live stays on v11."
    )
"""

SAVE_CELL = """shap_report = {}
if not train_hist.get("ok"):
    print("Skip save: training did not succeed", train_hist)
else:
    try:
        shap_report = shap_grouped_stub(
            feature_cols,
            enabled=bool(CONFIG.get("run_shap")),
            model=model,
            val_windows=splits["val"]["windows"],
            device=device,
            config=CONFIG,
        )
    except Exception as exc:
        print("SHAP failed; continuing export:", type(exc).__name__, exc)
        shap_report = {
            "ok": False,
            "enabled": True,
            "reason": f"{type(exc).__name__}: {exc}",
            "horizons": {},
        }
    artifact = {
        "feature_cols": list(feature_cols),
        "seed": CONFIG.get("seed"),
        "window_len": window_len,
        "window_lens": window_lens,
        "target_window_minutes": CONFIG.get("target_window_minutes"),
        "feature_contract_version": FEATURE_CONTRACT_VERSION_V15,
        "resolutions": list(FUSION_INPUT_RESOLUTIONS),
        "horizon_keys": list(LABEL_V2_HORIZON_KEYS),
        "tf_fusion_weights": [float(x) for x in fusion_w],
        "val_metrics": val_metrics,
        "horizon_gates": gates,
        "test_metrics": final_test,
        "shap_report": shap_report,
        "optuna_best": CONFIG.get("optuna_best"),
    }
    (export_dir / "research_run.json").write_text(
        json.dumps(artifact, indent=2, default=str), encoding="utf-8"
    )
    print("Wrote", export_dir / "research_run.json")
"""

EXPORT_CELL = """if not train_hist.get("ok"):
    print("Skip ONNX export: training did not succeed", train_hist)
else:
    if not shap_report:
        try:
            shap_report = shap_grouped_stub(
                feature_cols,
                enabled=bool(CONFIG.get("run_shap")),
                model=model,
                val_windows=splits["val"]["windows"],
                device=device,
                config=CONFIG,
            )
        except Exception as exc:
            print("SHAP retry failed; exporting anyway:", type(exc).__name__, exc)
            shap_report = {"ok": False, "reason": str(exc), "horizons": {}}
    onnx_path, cfg_path, meta_path = export_fusion_bundle(
        model,
        export_dir,
        n_features=n_features,
        window_lens=window_lens,
        window_len=window_len,
        config=CONFIG,
        gates=gates,
        fusion_weights=fusion_w.tolist(),
        test_metrics=final_test,
    )
    print("Exported", onnx_path)
    print("feature_config", cfg_path)
    print("metadata", meta_path)
    print("Do NOT copy this v15 bundle into agent/model_storage/. Live remains v11.")
    import shutil
    zip_stem = export_dir.parent / FUSION_V15_BUNDLE_DIR_NAME
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
- Training ``y`` is Label V2: 3-class direction (NEUTRAL trained) plus
  ret / long-short MFE/MAE.
- Persistence and TP/SL first-touch stay diagnostics, not loss heads.
- Export is v15 research-only. ``fusion_ready_to_promote`` is always false.
  Do **not** copy the bundle into ``agent/model_storage/``. Live stays on v11.
- Paper PnL is a secondary diagnostic, not the training loss.
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
        *_section("## 12 Optuna", OPTUNA_CELL),
        *_section("## 13 Fusion transformer", MODEL_CELL),
        *_section("## 14 Cross-entropy loss", LOSS_CELL),
        *_section("## 15 Train + early stopping", TRAIN_CELL),
        *_section("## 16 Validation metrics", VAL_CELL),
        *_section("## 17 Test hold", TEST_CELL),
        *_section("## 18 Walk-forward", WALK_CELL),
        *_section("## 19 Horizon confusion", CONFUSION_CELL),
        *_section("## 20 Fusion weights", WEIGHTS_CELL),
        *_section("## 21 Temperature calibration", CALIBRATION_CELL),
        *_section("## 22 Horizon grades", GRADES_CELL),
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
