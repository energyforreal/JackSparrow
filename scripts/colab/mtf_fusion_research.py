"""Training, walk-forward validation, and ONNX export for the fused MTF model.

Walk-forward and Optuna see only development/validation folds. The held-out
test split is scored once after freeze.
"""

from __future__ import annotations

import gc
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader

from feature_store.transformer_btcusd.contract import (
    FUSION_BUNDLE_DIR_NAME,
    FUSION_DIRECTION_CARDINALITY,
    FUSION_DIRECTION_NAMES,
    FUSION_GRADE_HIGH,
    FUSION_GRADE_LOW,
    FUSION_GRADE_MEDIUM,
    FUSION_HIGH_BALANCED_ACC,
    FUSION_HIGH_MAX_ECE,
    FUSION_HORIZON_KEYS,
    FUSION_DIR_COLS,
    FUSION_INPUT_RESOLUTIONS,
    FUSION_MEDIUM_BALANCED_ACC,
    FUSION_MIN_PROBABILITY,
    FUSION_MODEL_FAMILY,
    FUSION_ONNX_FILENAME,
    FUSION_WINDOW_LEN,
    FEATURE_CONTRACT_VERSION_V11,
    ONNX_OUTPUT_NAMES_V11,
    TRANSFORMER_FEATURE_CONFIG_FILENAME,
    TRANSFORMER_METADATA_FILENAME,
    default_fusion_training_config,
)
from feature_store.transformer_btcusd.mtf_features import (
    collect_training_windows,
    fusion_feature_cols,
    precompute_featured_frames,
)
from feature_store.transformer_btcusd.mtf_frames import bar_close_time
from feature_store.transformer_btcusd.mtf_labels import (
    compute_fusion_horizon_labels,
    fusion_future_leak_cols,
    fusion_label_matrix,
    label_class_mix,
    trim_fusion_label_tail,
    valid_label_mask,
)
from scripts.colab.mtf_fusion_model import (
    MtfFusionDataset,
    MtfFusionTransformer,
    inverse_frequency_class_weights,
    train_mtf_fusion,
)


def set_research_seed(seed: int) -> None:
    """Seed numpy and torch for Colab reproducibility."""
    np.random.seed(int(seed))
    torch.manual_seed(int(seed))
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(int(seed))


def walk_forward_slices(
    n: int,
    *,
    folds: int,
    embargo: int,
) -> List[Tuple[slice, slice]]:
    """Expanding train, trailing val; never includes a held-out final test."""
    folds = max(int(folds), 1)
    out: List[Tuple[slice, slice]] = []
    for i in range(folds):
        train_end = max(2, int(n * (0.50 + 0.10 * i)))
        val_end = min(n, train_end + max(int(n * 0.12), 8))
        gap = min(max(int(embargo), 0), max(0, val_end - train_end - 1))
        val_start = train_end + gap
        if val_start >= val_end:
            continue
        out.append((slice(0, train_end), slice(val_start, val_end)))
    return out


def split_purged_windows(
    arrays: Mapping[str, np.ndarray],
    *,
    train_frac: float,
    val_frac: float,
    embargo_bars: int,
) -> Dict[str, Dict[str, np.ndarray]]:
    """Time-ordered train/val/test split with embargo gaps between segments."""
    if not arrays:
        raise ValueError("split_purged_windows requires at least one array")
    lengths = {k: len(v) for k, v in arrays.items()}
    n = next(iter(lengths.values()))
    if any(length != n for length in lengths.values()):
        raise ValueError(f"Array length mismatch: {lengths}")
    train_end = int(n * train_frac)
    val_end = train_end + int(n * val_frac)
    embargo = int(embargo_bars)
    slices = {
        "train": slice(0, train_end),
        "val": slice(train_end + embargo, val_end),
        "test": slice(val_end + embargo, n),
    }
    splits = {
        split: {k: v[sl] for k, v in arrays.items()} for split, sl in slices.items()
    }
    first_key = next(iter(arrays))
    if len(splits["train"][first_key]) == 0 or len(splits["val"][first_key]) == 0:
        raise ValueError(
            f"Insufficient windows after split: train={len(splits['train'][first_key])}, "
            f"val={len(splits['val'][first_key])}, test={len(splits['test'][first_key])}"
        )
    return splits


def leakage_audit(feature_cols: Sequence[str]) -> None:
    """Raise if any target or future column leaked into the input feature list.

    Causal structure fields such as ``last_swing_dir`` are valid inputs. Only
    horizon targets, resampled HTF columns, and explicit future_* names are banned.
    """
    banned = set(fusion_future_leak_cols())
    leaked: List[str] = []
    for col in feature_cols:
        name = str(col)
        if (
            name in banned
            or name.startswith("htf_")
            or name.startswith("future_")
            or name.startswith("horizon_")
        ):
            leaked.append(name)
    if leaked:
        raise RuntimeError(f"Future/HTF/target columns in inputs: {leaked}")
    print("Leakage audit passed: no horizon dirs, no resampled HTF structure in X.")


def confusion_counts(pred: np.ndarray, true: np.ndarray, n_classes: int) -> np.ndarray:
    """Integer confusion matrix (rows=true, cols=pred)."""
    mat = np.zeros((n_classes, n_classes), dtype=np.int64)
    pred_i = np.asarray(pred, dtype=np.int64)
    true_i = np.asarray(true, dtype=np.int64)
    for t, p in zip(true_i, pred_i):
        if 0 <= t < n_classes and 0 <= p < n_classes:
            mat[t, p] += 1
    return mat


def feature_finite_report(
    values: np.ndarray,
    feature_cols: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Print finite-rate before training. Does not mutate caller arrays."""
    arr = np.asarray(values, dtype=np.float64)
    finite_rate = float(np.isfinite(arr).mean()) if arr.size else 1.0
    n_inf = int(np.isinf(arr).sum())
    n_nan = int(np.isnan(arr).sum())
    print(f"feature finite_rate={finite_rate:.4f} inf={n_inf} nan={n_nan}")
    if feature_cols is not None:
        print(f"n_features={len(feature_cols)}")
    return {"finite_rate": finite_rate, "inf": n_inf, "nan": n_nan}


def shap_grouped_stub(
    feature_cols: Sequence[str], *, enabled: bool
) -> Dict[str, List[str]]:
    """Grouped feature names for optional SHAP. Skip compute unless enabled."""
    groups = {
        "candle": [c for c in feature_cols if "cdl_" in c or "body" in c or "wick" in c],
        "chart": [c for c in feature_cols if c.startswith(("sr_", "tl_", "chp_"))],
        "trend": [c for c in feature_cols if "ema" in c or c in ("macd_hist", "adx_14", "rsi_14")],
        "vol": [c for c in feature_cols if "atr" in c or c.startswith("rv_")],
        "htf_resample": [c for c in feature_cols if str(c).startswith("htf_")],
    }
    if not enabled:
        print("SHAP skipped (CONFIG run_shap=False). Fusion feature groups:")
        for name, cols in groups.items():
            print(f"  {name}: {len(cols)} cols")
        if groups["htf_resample"]:
            raise RuntimeError("htf_ columns must not appear in fusion inputs")
        return groups
    print("SHAP enabled — install shap in Colab and call shap.Explainer on a loader.")
    return groups


def optuna_search_stub(config: Mapping[str, Any]) -> Dict[str, Any]:
    """Optuna on walk-forward validation only. Never uses the final test split."""
    cfg = dict(config)
    if not cfg.get("run_optuna"):
        print(
            "Optuna skipped (CONFIG run_optuna=False). "
            "Search space: lr, weight_decay, dropout, layers, d_model, batch."
        )
        return cfg
    try:
        import optuna  # noqa: F401
    except ImportError:
        print("Optuna not installed; leaving CONFIG unchanged.")
        return cfg
    print("Optuna enabled — objective must be walk-forward val CE, never test.")
    return cfg


def _decision_times(featured_5m: pd.DataFrame, window_len: int) -> pd.Series:
    times = pd.to_datetime(featured_5m["time"], utc=True)
    return times.iloc[int(window_len) :]


def build_dataset_from_ohlcv(
    frames: Dict[str, pd.DataFrame],
    *,
    window_len: int = FUSION_WINDOW_LEN,
    stride: int = 4,
    memmap_dir: Optional[Path] = None,
) -> Tuple[Dict[str, np.ndarray], np.ndarray, pd.Series]:
    """Native TF windows + 2-class train labels aligned on the 5m decision clock."""
    labeled = compute_fusion_horizon_labels(frames["5m"])
    labeled = trim_fusion_label_tail(labeled)
    featured = precompute_featured_frames(frames)
    feat5_time = featured["5m"][["time"]].copy()
    feat5_time["time"] = pd.to_datetime(feat5_time["time"], utc=True)
    labeled["time"] = pd.to_datetime(labeled["time"], utc=True)
    dir_cols = [c for c in FUSION_DIR_COLS if c in labeled.columns]
    merged = feat5_time.merge(labeled[["time", *dir_cols]], on="time", how="inner")
    merged = merged.iloc[int(window_len) :].reset_index(drop=True)
    if stride > 1:
        merged = merged.iloc[:: int(stride)].reset_index(drop=True)
    y = fusion_label_matrix(merged)
    mask = valid_label_mask(y)
    merged = merged.loc[mask].reset_index(drop=True)
    y = y[mask]
    decision_close = bar_close_time(merged["time"], 5)
    windows = collect_training_windows(
        featured,
        list(decision_close),
        window_len=window_len,
        zscore=True,
        memmap_dir=memmap_dir,
    )
    decision_times = merged["time"].copy()
    del featured, labeled, merged, feat5_time
    gc.collect()
    return windows, y, decision_times


def softmax_np(logits: np.ndarray) -> np.ndarray:
    z = logits - np.max(logits, axis=-1, keepdims=True)
    exp = np.exp(z)
    return exp / np.clip(exp.sum(axis=-1, keepdims=True), 1e-12, None)


def balanced_accuracy(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    n_classes: int = FUSION_DIRECTION_CARDINALITY,
) -> float:
    scores: List[float] = []
    for c in range(int(n_classes)):
        mask = y_true == c
        if not np.any(mask):
            continue
        scores.append(float(np.mean(y_pred[mask] == c)))
    if not scores:
        return 0.0
    return float(np.mean(scores))


def macro_f1(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    n_classes: int = FUSION_DIRECTION_CARDINALITY,
) -> float:
    f1s: List[float] = []
    for c in range(int(n_classes)):
        tp = float(np.sum((y_true == c) & (y_pred == c)))
        fp = float(np.sum((y_true != c) & (y_pred == c)))
        fn = float(np.sum((y_true == c) & (y_pred != c)))
        prec = tp / (tp + fp + 1e-9)
        rec = tp / (tp + fn + 1e-9)
        f1s.append(2 * prec * rec / (prec + rec + 1e-9))
    return float(np.mean(f1s)) if f1s else 0.0


def expected_calibration_error(
    probs: np.ndarray,
    y_true: np.ndarray,
    n_bins: int = 10,
) -> float:
    """ECE on max-class confidence vs correctness."""
    conf = probs.max(axis=-1)
    pred = probs.argmax(axis=-1)
    correct = (pred == y_true).astype(np.float64)
    edges = np.linspace(0.0, 1.0, int(n_bins) + 1)
    ece = 0.0
    n = max(len(y_true), 1)
    for i in range(int(n_bins)):
        lo, hi = edges[i], edges[i + 1]
        if i == n_bins - 1:
            sel = (conf >= lo) & (conf <= hi)
        else:
            sel = (conf >= lo) & (conf < hi)
        if not np.any(sel):
            continue
        acc = float(correct[sel].mean())
        avg_conf = float(conf[sel].mean())
        ece += (float(sel.sum()) / n) * abs(acc - avg_conf)
    return float(ece)


def brier_score(
    probs: np.ndarray,
    y_true: np.ndarray,
    n_classes: int = FUSION_DIRECTION_CARDINALITY,
) -> float:
    onehot = np.eye(int(n_classes), dtype=np.float64)[np.clip(y_true, 0, n_classes - 1)]
    return float(np.mean(np.sum((probs - onehot) ** 2, axis=-1)))


def paper_pnl(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Secondary metric only. +1 correct 2-class direction, -1 wrong. Skip < 0."""
    valid = (y_true >= 0) & (y_pred >= 0)
    if not np.any(valid):
        return 0.0
    wins = y_pred[valid] == y_true[valid]
    return float(np.mean(np.where(wins, 1.0, -1.0)))


def fit_temperature(logits: np.ndarray, y_true: np.ndarray) -> float:
    """One-parameter temperature on validation logits (NLL). Never uses test."""
    valid = y_true >= 0
    if not np.any(valid):
        return 1.0
    z = torch.tensor(logits[valid], dtype=torch.float32)
    y = torch.tensor(y_true[valid], dtype=torch.long)
    log_t = torch.nn.Parameter(torch.zeros(()))
    opt = torch.optim.LBFGS([log_t], lr=0.25, max_iter=50)

    def _closure() -> torch.Tensor:
        opt.zero_grad()
        temp = torch.exp(log_t).clamp(0.05, 10.0)
        loss = torch.nn.functional.cross_entropy(z / temp, y)
        loss.backward()
        return loss

    opt.step(_closure)
    return float(torch.exp(log_t).clamp(0.05, 10.0).detach().item())


def apply_temperature(logits: np.ndarray, temperature: float) -> np.ndarray:
    t = max(float(temperature), 1e-6)
    return softmax_np(logits / t)


def grade_horizon(
    *,
    balanced_acc: float,
    ece: float,
    fold_std: float = 0.0,
    high_acc: float = FUSION_HIGH_BALANCED_ACC,
    high_ece: float = FUSION_HIGH_MAX_ECE,
    medium_acc: float = FUSION_MEDIUM_BALANCED_ACC,
) -> str:
    """Map OOS metrics to HIGH / MEDIUM / LOW. Unstable folds cannot be HIGH."""
    if float(fold_std) > 0.08:
        if float(balanced_acc) >= float(medium_acc):
            return FUSION_GRADE_MEDIUM
        return FUSION_GRADE_LOW
    if float(balanced_acc) >= float(high_acc) and float(ece) <= float(high_ece):
        return FUSION_GRADE_HIGH
    if float(balanced_acc) >= float(medium_acc):
        return FUSION_GRADE_MEDIUM
    return FUSION_GRADE_LOW


def horizon_metrics(
    logits: np.ndarray,
    y_true: np.ndarray,
    *,
    temperature: float = 1.0,
) -> Dict[str, float]:
    valid = y_true >= 0
    if not np.any(valid):
        return {
            "balanced_acc": 0.0,
            "macro_f1": 0.0,
            "ece": 1.0,
            "brier": 1.0,
            "paper_pnl": 0.0,
            "n": 0.0,
        }
    probs = apply_temperature(logits[valid], temperature)
    pred = probs.argmax(axis=-1)
    yt = y_true[valid]
    return {
        "balanced_acc": balanced_accuracy(yt, pred, FUSION_DIRECTION_CARDINALITY),
        "macro_f1": macro_f1(yt, pred, FUSION_DIRECTION_CARDINALITY),
        "ece": expected_calibration_error(probs, yt),
        "brier": brier_score(probs, yt, FUSION_DIRECTION_CARDINALITY),
        "paper_pnl": paper_pnl(yt, pred),
        "n": float(len(yt)),
    }


@torch.no_grad()
def predict_logits(
    model: MtfFusionTransformer,
    loader: DataLoader,
    device: torch.device,
) -> Tuple[np.ndarray, np.ndarray]:
    """Return (n, n_horizons, 2) logits and (n, n_horizons) labels."""
    model.eval()
    logit_chunks: List[np.ndarray] = []
    label_chunks: List[np.ndarray] = []
    for batch in loader:
        batch_d = tuple(t.to(device) for t in batch)
        outs = model(*batch_d[:-1])
        dir_logits = [o.cpu().numpy() for o in outs[:N_HORIZONS_SAFE]]
        stacked = np.stack(dir_logits, axis=1)
        logit_chunks.append(stacked)
        label_chunks.append(batch_d[-1].cpu().numpy())
    return np.concatenate(logit_chunks, axis=0), np.concatenate(label_chunks, axis=0)


N_HORIZONS_SAFE = len(FUSION_HORIZON_KEYS)


def slice_windows(
    windows: Mapping[str, np.ndarray],
    labels: np.ndarray,
    sl: slice,
) -> Tuple[Dict[str, np.ndarray], np.ndarray]:
    return {k: v[sl] for k, v in windows.items()}, labels[sl]


def make_loader(
    windows: Mapping[str, np.ndarray],
    labels: np.ndarray,
    *,
    batch_size: int,
    shuffle: bool,
) -> DataLoader:
    ds = MtfFusionDataset(dict(windows), labels)
    return DataLoader(ds, batch_size=int(batch_size), shuffle=shuffle)


def run_walk_forward(
    windows: Mapping[str, np.ndarray],
    labels: np.ndarray,
    *,
    n_features: int,
    config: Mapping[str, Any],
    device: torch.device,
) -> Dict[str, Any]:
    """Expanding-window folds on the development set only."""
    n = len(labels)
    folds = int(
        config.get("walk_forward_folds") or config.get("walk_forward_folds") or 3
    )
    embargo = int(
        config.get("walk_forward_embargo") or config.get("walk_forward_embargo") or 24
    )
    fold_rows: List[Dict[str, Any]] = []
    per_h_acc: Dict[str, List[float]] = {k: [] for k in FUSION_HORIZON_KEYS}
    for train_sl, val_sl in walk_forward_slices(n, folds=folds, embargo=embargo):
        tw, ty = slice_windows(windows, labels, train_sl)
        vw, vy = slice_windows(windows, labels, val_sl)
        model = MtfFusionTransformer(n_features=n_features).to(device)
        train_loader = make_loader(tw, ty, batch_size=int(config.get("batch_size") or 64), shuffle=True)
        val_loader = make_loader(vw, vy, batch_size=int(config.get("batch_size") or 64), shuffle=False)
        train_mtf_fusion(
            model,
            train_loader,
            val_loader,
            device=device,
            epochs=max(1, int(config.get("epochs") or 8) // 4),
            lr=float(config.get("lr") or 1e-4),
            weight_decay=float(config.get("weight_decay") or 1e-4),
            patience=max(2, int(config.get("early_stop_patience") or 8) // 2),
        )
        logits, y = predict_logits(model, val_loader, device)
        row: Dict[str, Any] = {}
        for j, key in enumerate(FUSION_HORIZON_KEYS):
            m = horizon_metrics(logits[:, j, :], y[:, j])
            row[key] = m
            per_h_acc[key].append(float(m["balanced_acc"]))
        fold_rows.append(row)
    summary: Dict[str, Any] = {"folds": fold_rows, "mean": {}, "std": {}}
    for key in FUSION_HORIZON_KEYS:
        vals = per_h_acc[key]
        summary["mean"][key] = float(np.mean(vals)) if vals else 0.0
        summary["std"][key] = float(np.std(vals)) if vals else 0.0
    return summary


def freeze_horizon_gates(
    val_logits: np.ndarray,
    val_y: np.ndarray,
    walk_forward: Mapping[str, Any],
    *,
    config: Mapping[str, Any],
) -> Dict[str, Any]:
    """Calibrate and grade each horizon on validation. Do not touch test."""
    gates: Dict[str, Any] = {}
    temps: Dict[str, float] = {}
    for j, key in enumerate(FUSION_HORIZON_KEYS):
        temp = fit_temperature(val_logits[:, j, :], val_y[:, j])
        temps[key] = temp
        m = horizon_metrics(val_logits[:, j, :], val_y[:, j], temperature=temp)
        fold_std = float((walk_forward.get("std") or {}).get(key) or 0.0)
        grade = grade_horizon(
            balanced_acc=float(m["balanced_acc"]),
            ece=float(m["ece"]),
            fold_std=fold_std,
            high_acc=float(config.get("high_balanced_acc") or FUSION_HIGH_BALANCED_ACC),
            high_ece=float(config.get("high_max_ece") or FUSION_HIGH_MAX_ECE),
            medium_acc=float(config.get("medium_balanced_acc") or FUSION_MEDIUM_BALANCED_ACC),
        )
        gates[key] = {
            **m,
            "temperature": temp,
            "validation_confidence": grade,
            "min_probability": float(config.get("min_probability") or FUSION_MIN_PROBABILITY),
            "accepted_grades": [FUSION_GRADE_HIGH, FUSION_GRADE_MEDIUM],
        }
    return {"horizons": gates, "temperatures": temps}


def export_fusion_bundle(
    model: MtfFusionTransformer,
    export_dir: Path,
    *,
    n_features: int,
    window_len: int,
    config: Mapping[str, Any],
    gates: Mapping[str, Any],
    fusion_weights: Sequence[float],
    test_metrics: Mapping[str, Any] | None = None,
) -> Tuple[Path, Path, Path]:
    """Write ONNX + feature_config + metadata for the single fused bundle."""
    export_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = export_dir / FUSION_ONNX_FILENAME
    cfg_path = export_dir / TRANSFORMER_FEATURE_CONFIG_FILENAME
    meta_path = export_dir / TRANSFORMER_METADATA_FILENAME
    dummy = [
        torch.randn(1, int(window_len), int(n_features)) for _ in FUSION_INPUT_RESOLUTIONS
    ]
    input_names = [f"features_{res}" for res in FUSION_INPUT_RESOLUTIONS]
    output_names = list(ONNX_OUTPUT_NAMES_V11)
    dynamic_axes = {name: {0: "batch"} for name in input_names + output_names}
    model.cpu().eval()
    export_kwargs: Dict[str, Any] = {
        "input_names": input_names,
        "output_names": output_names,
        "dynamic_axes": dynamic_axes,
        "opset_version": 17,
        "export_params": True,
    }
    last_error: Optional[BaseException] = None
    exported = False
    for opset in (17, 14):
        export_kwargs["opset_version"] = int(opset)
        try:
            try:
                torch.onnx.export(
                    model,
                    tuple(dummy),
                    str(onnx_path),
                    dynamo=False,
                    **export_kwargs,
                )
            except TypeError:
                torch.onnx.export(
                    model, tuple(dummy), str(onnx_path), **export_kwargs
                )
            exported = True
            break
        except (TypeError, RuntimeError, ValueError) as exc:
            last_error = exc
    if not exported:
        raise RuntimeError(
            f"ONNX export failed for opset 17 and 14: {last_error}"
        ) from last_error
    try:
        import onnx

        onnx.checker.check_model(onnx.load(str(onnx_path)))
    except ImportError:
        pass

    feature_config = {
        "feature_contract_version": FEATURE_CONTRACT_VERSION_V11,
        "feature_cols": list(fusion_feature_cols()),
        "window_len": int(window_len),
        "resolutions": list(FUSION_INPUT_RESOLUTIONS),
        "horizon_keys": list(FUSION_HORIZON_KEYS),
        "direction_names": {str(k): v for k, v in FUSION_DIRECTION_NAMES.items()},
        "onnx_output_names": output_names,
        "input_names": input_names,
        "config": dict(config),
        "horizon_gates": dict(gates),
        "tf_fusion_weights": [float(x) for x in fusion_weights],
    }
    cfg_path.write_text(
        json.dumps(feature_config, indent=2, default=str), encoding="utf-8"
    )
    meta = {
        "version": "transformer_mtf_fusion_v11",
        "model_name": "jacksparrow_transformer_BTCUSD_mtf_fusion",
        "model_family": FUSION_MODEL_FAMILY,
        "symbol": str(config.get("symbol") or "BTCUSD"),
        "resolution": "mtf_fusion",
        "onnx_filename": FUSION_ONNX_FILENAME,
        "feature_config_filename": TRANSFORMER_FEATURE_CONFIG_FILENAME,
        "onnx_output_names": output_names,
        "tf_fusion_weights": [float(x) for x in fusion_weights],
        "horizon_gates": dict(gates),
        "test_metrics": dict(test_metrics or {}),
        "training_config": dict(config),
        "primary_signal_mode": "multi_horizon_position",
    }
    meta_path.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    return onnx_path, cfg_path, meta_path


def purged_dev_test_split(
    windows: Mapping[str, np.ndarray],
    labels: np.ndarray,
    *,
    train_frac: float,
    val_frac: float,
    embargo_bars: int,
) -> Dict[str, Dict[str, np.ndarray]]:
    """Time-ordered train/val/test with embargo. Test is the final untouched tail."""
    packed = {**{f"x_{k}": v for k, v in windows.items()}, "y": labels}
    splits = split_purged_windows(
        packed, train_frac=train_frac, val_frac=val_frac, embargo_bars=embargo_bars
    )
    out: Dict[str, Dict[str, np.ndarray]] = {}
    for name, part in splits.items():
        out[name] = {
            "windows": {res: part[f"x_{res}"] for res in FUSION_INPUT_RESOLUTIONS},
            "labels": part["y"],
        }
    return out


def fusion_ready_to_promote(
    walk_forward: Mapping[str, Any],
    test_metrics: Mapping[str, Any],
    gates: Mapping[str, Any],
) -> Dict[str, Any]:
    """True if at least one head is MEDIUM+ on walk-forward mean and frozen test.

    HIGH still requires ECE and fold std via ``grade_horizon``. Live must not
    load a bundle when this returns ready=False.
    """
    wf_mean = dict(walk_forward.get("mean") or {})
    wf_std = dict(walk_forward.get("std") or {})
    gate_map = dict(gates.get("horizons") or gates)
    ready_heads: List[str] = []
    detail: Dict[str, Any] = {}
    for key in FUSION_HORIZON_KEYS:
        test_m = dict(test_metrics.get(key) or {})
        test_acc = float(test_m.get("balanced_acc") or 0.0)
        test_ece = float(test_m.get("ece") or 1.0)
        wf_acc = float(wf_mean.get(key) or 0.0)
        fold_std = float(wf_std.get(key) or 0.0)
        wf_grade = grade_horizon(
            balanced_acc=wf_acc,
            ece=test_ece,
            fold_std=fold_std,
        )
        test_grade = str(
            (gate_map.get(key) or {}).get("validation_confidence") or ""
        )
        if not test_grade:
            test_grade = grade_horizon(balanced_acc=test_acc, ece=test_ece)
        accepted = {FUSION_GRADE_HIGH, FUSION_GRADE_MEDIUM}
        ok = wf_grade in accepted and test_grade in accepted
        if ok:
            ready_heads.append(key)
        detail[key] = {
            "walk_forward_mean_acc": wf_acc,
            "walk_forward_grade": wf_grade,
            "test_acc": test_acc,
            "test_grade": test_grade,
            "ok": ok,
        }
    ready = bool(ready_heads)
    return {
        "ready": ready,
        "heads": ready_heads,
        "detail": detail,
        "reason": (
            "at least one head MEDIUM+ on walk-forward mean and frozen test"
            if ready
            else "no head is MEDIUM on walk-forward mean and frozen test; do not promote"
        ),
    }


def default_config() -> Dict[str, Any]:
    cfg = default_fusion_training_config()
    cfg["window_len"] = FUSION_WINDOW_LEN
    cfg["n_classes"] = FUSION_DIRECTION_CARDINALITY
    return cfg
