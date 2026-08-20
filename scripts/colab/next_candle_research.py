"""Research pipeline: multi-horizon 5m path training for the Transformer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader

from feature_store.transformer_btcusd.contract import (
    CANDLE_CLASS_COL,
    CHART_PATTERN_COL,
    FEATURE_CONTRACT_VERSION,
    HORIZON_DIR_COLS,
    HORIZON_KEYS,
    HORIZON_STRUCTURE_COLS,
    MAX_V8_HORIZON_BARS,
    N_HORIZONS,
    ONNX_OUTPUT_NAMES_V8,
    V8_CONTINUOUS_LABEL_COLS,
    VOLUME_STATE_COL,
    ablation_feature_groups,
    default_research_config,
    v8_feature_cols_for_resolution,
    v8_future_leak_cols,
)
from feature_store.transformer_btcusd.features import add_features, assemble_raw_frame
from feature_store.transformer_btcusd.inference import (
    feature_config_from_training_export,
    metadata_from_training_export,
)
from feature_store.transformer_btcusd.labels import (
    compute_horizon_behavior_labels,
    trim_v8_label_tail,
)
from scripts.colab.next_candle_model import (
    NextCandleDataset,
    NextCandleTransformer,
    train_next_candle,
)
from scripts.colab.transformer_data import (
    _bar_seconds,
    fetch_history_bundle,
    validate_ohlcv_completeness,
)


FUTURE_LEAK_COLS = v8_future_leak_cols()


def set_research_seed(seed: int) -> None:
    """Seed numpy and torch for Colab reproducibility."""
    np.random.seed(int(seed))
    torch.manual_seed(int(seed))
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(int(seed))


def ohlcv_quality_report(
    df: pd.DataFrame,
    resolution: str,
    *,
    min_completeness: float = 0.95,
    symbol: str = "BTCUSD",
) -> Dict[str, Any]:
    """Timestamp, duplicate, OHLC-validity, and gap report. Does not mutate OHLC."""
    if df is None or df.empty:
        raise ValueError("OHLCV frame is empty")
    frame = df.copy()
    if "time" not in frame.columns:
        raise ValueError("OHLCV requires a time column")
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    n = len(frame)
    dupes = int(frame["time"].duplicated().sum())
    unsorted = not bool(frame["time"].is_monotonic_increasing)
    invalid = 0
    if all(c in frame.columns for c in ("open", "high", "low", "close")):
        invalid = int(
            (
                (frame["high"] < frame["low"])
                | (frame["high"] < frame["open"])
                | (frame["high"] < frame["close"])
                | (frame["low"] > frame["open"])
                | (frame["low"] > frame["close"])
            ).sum()
        )
    neg_vol = 0
    if "volume" in frame.columns:
        neg_vol = int((frame["volume"] < 0).sum())
    nan_cells = int(frame.isna().sum().sum())
    sorted_t = frame.sort_values("time")["time"]
    deltas = sorted_t.diff().dt.total_seconds().dropna()
    bar_sec = float(_bar_seconds(resolution))
    missing = int(np.maximum((deltas / bar_sec) - 1.0, 0.0).round().sum())
    completeness = validate_ohlcv_completeness(
        frame.sort_values("time"),
        resolution,
        min_completeness=min_completeness,
        symbol=symbol,
    )
    report = {
        "rows": n,
        "time_start": str(frame["time"].min()),
        "time_end": str(frame["time"].max()),
        "duplicates": dupes,
        "unsorted": unsorted,
        "invalid_ohlc": invalid,
        "negative_volume": neg_vol,
        "nans": nan_cells,
        "missing_candles": missing if missing else completeness.get("gaps", 0),
        "completeness": completeness.get("completeness"),
    }
    print(
        "OHLCV quality: "
        f"rows={n} range={report['time_start']} → {report['time_end']} "
        f"missing={report['missing_candles']} dupes={dupes} "
        f"invalid_ohlc={invalid} nans={nan_cells}"
    )
    if dupes or invalid or neg_vol:
        raise ValueError(f"OHLCV quality failed: {report}")
    return report


def leakage_audit(feature_cols: Sequence[str]) -> None:
    """Raise if any target/future column leaked into the input feature list."""
    leaked = [c for c in feature_cols if c in FUTURE_LEAK_COLS]
    if leaked:
        raise RuntimeError(f"Future/target columns in inputs: {leaked}")


def chronological_split(
    n: int,
    *,
    train_ratio: float,
    validation_ratio: float,
    embargo: int,
) -> Dict[str, slice]:
    """Time-ordered train/val/test slices with an embargo gap.

    Embargo shrinks when the split would otherwise empty val or test.
    """
    n = int(n)
    train_end = max(1, int(n * float(train_ratio)))
    val_span = max(1, int(n * float(validation_ratio)))
    val_end = min(n, train_end + val_span)
    if val_end <= train_end:
        val_end = min(n, train_end + 1)
    gap = max(int(embargo), 0)
    gap = min(gap, max(0, val_end - train_end - 1), max(0, n - val_end - 1))
    val_start = train_end + gap
    test_start = val_end + gap
    if val_start >= val_end:
        val_start = train_end
    if test_start >= n:
        test_start = val_end
    return {
        "train": slice(0, train_end),
        "val": slice(val_start, val_end),
        "test": slice(test_start, n),
    }


def sanitize_feature_values(values: np.ndarray) -> np.ndarray:
    """Replace inf with NaN, then fill remaining NaNs with 0. Always finite."""
    cleaned = np.asarray(values, dtype=np.float64).copy()
    cleaned[~np.isfinite(cleaned)] = np.nan
    return np.nan_to_num(cleaned, nan=0.0, posinf=0.0, neginf=0.0)


def feature_finite_report(
    values: np.ndarray,
    feature_cols: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Print finite-rate and per-column inf/nan counts before sanitizing."""
    arr = np.asarray(values, dtype=np.float64)
    finite_rate = float(np.isfinite(arr).mean()) if arr.size else 1.0
    n_inf = int(np.isinf(arr).sum())
    n_nan = int(np.isnan(arr).sum())
    bad_cols: List[Dict[str, Any]] = []
    if arr.ndim == 2 and arr.shape[1] > 0:
        names: Sequence[str]
        if feature_cols is not None and len(feature_cols) == arr.shape[1]:
            names = feature_cols
        else:
            names = [f"c{i}" for i in range(arr.shape[1])]
        for i, name in enumerate(names):
            col = arr[:, i]
            c_inf = int(np.isinf(col).sum())
            c_nan = int(np.isnan(col).sum())
            if c_inf or c_nan:
                bad_cols.append({"col": str(name), "inf": c_inf, "nan": c_nan})
    report = {
        "finite_rate": finite_rate,
        "inf": n_inf,
        "nan": n_nan,
        "bad_cols": bad_cols,
    }
    print(
        f"feature finite_rate={finite_rate:.6f} inf={n_inf} nan={n_nan} "
        f"bad_cols={len(bad_cols)}"
    )
    for item in bad_cols[:12]:
        print(f"  {item['col']}: inf={item['inf']} nan={item['nan']}")
    if len(bad_cols) > 12:
        print(f"  ... {len(bad_cols) - 12} more columns")
    return report


def fit_label_stats(y_train: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Train-split mean/std for path-label standardization (NaNs excluded)."""
    mean = np.nan_to_num(np.nanmean(y_train, axis=0), nan=0.0)
    std = np.nan_to_num(np.nanstd(y_train, axis=0), nan=1.0) + 1e-9
    return mean.astype(np.float64), std.astype(np.float64)


def standardize_labels(
    y: np.ndarray,
    label_mean: np.ndarray,
    label_std: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    """Z-score path labels and build per-target validity masks."""
    mask = (~np.isnan(y)).astype(np.float32)
    yz = np.where(np.isnan(y), 0.0, (y - label_mean) / label_std).astype(np.float32)
    return yz, mask


def fit_train_scaler(
    train_values: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    """Column mean/std from TRAIN rows only."""
    cleaned = sanitize_feature_values(train_values)
    mean = np.nanmean(cleaned, axis=0)
    std = np.nanstd(cleaned, axis=0) + 1e-6
    return mean.astype(np.float32), std.astype(np.float32)


def apply_scaler(
    values: np.ndarray,
    mean: np.ndarray,
    std: np.ndarray,
) -> np.ndarray:
    """Apply a frozen train scaler. Does not refit."""
    return ((values - mean) / std).astype(np.float32)


def build_labeled_frame(
    raw: pd.DataFrame,
    *,
    config: Mapping[str, Any],
) -> pd.DataFrame:
    """Causal features + v8 multi-horizon behavior labels. Raw OHLCV is copied."""
    resolution_minutes = int(config.get("resolution_minutes") or 5)
    atr_period = int(config.get("atr_period") or 14)
    feat = add_features(
        assemble_raw_frame(raw),
        resolution_minutes=resolution_minutes,
        atr_period=atr_period,
    )
    labeled = compute_horizon_behavior_labels(feat)
    return trim_v8_label_tail(labeled)


def _stack_windows(
    values: np.ndarray,
    ids: np.ndarray,
    window_len: int,
    stride: int,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    x_list: List[np.ndarray] = []
    cat_list: List[np.ndarray] = []
    ends: List[int] = []
    for end in range(window_len, len(values), stride):
        start = end - window_len
        x_list.append(values[start:end])
        cat_list.append(ids[start:end])
        ends.append(end - 1)
    return (
        np.array(x_list, dtype=np.float32),
        np.array(cat_list, dtype=np.int64),
        np.array(ends, dtype=np.int64),
    )


def windows_from_frame(
    df: pd.DataFrame,
    *,
    feature_cols: Sequence[str],
    window_len: int,
    stride: int,
    scaler_mean: Optional[np.ndarray] = None,
    scaler_std: Optional[np.ndarray] = None,
    per_window_zscore: bool = False,
) -> Dict[str, np.ndarray]:
    """Build overlapping windows with labels taken at the last bar of each window."""
    leakage_audit(feature_cols)
    values = sanitize_feature_values(df[list(feature_cols)].to_numpy(dtype=np.float64))
    if scaler_mean is not None and scaler_std is not None:
        values = sanitize_feature_values(apply_scaler(values, scaler_mean, scaler_std))
    ids = (
        df[CANDLE_CLASS_COL].to_numpy(dtype=np.int64)
        if CANDLE_CLASS_COL in df.columns
        else np.zeros(len(df), dtype=np.int64)
    )
    x, x_cat, idx = _stack_windows(values, ids, window_len, stride)

    def _take(col: str, default: float = 0.0) -> np.ndarray:
        if col not in df.columns:
            return np.full(len(idx), default)
        arr = df[col].to_numpy()[idx]
        return np.nan_to_num(arr, nan=default)

    path = np.column_stack(
        [_take(c, np.nan) for c in V8_CONTINUOUS_LABEL_COLS]
    ).astype(np.float64)
    horizon_dirs = np.column_stack(
        [_take(c, 1.0) for c in HORIZON_DIR_COLS]
    ).astype(np.int64)
    horizon_structs = np.column_stack(
        [_take(c, 0.0) for c in HORIZON_STRUCTURE_COLS]
    ).astype(np.int64)
    return {
        "x": x,
        "x_cat": x_cat,
        "idx": idx,
        "y_path": path,
        "volume_state": _take(VOLUME_STATE_COL, 1.0).astype(np.int64),
        "horizon_dirs": np.clip(horizon_dirs, 0, 2),
        "horizon_structs": np.clip(horizon_structs, 0, 5),
        "per_window_zscore": np.array([per_window_zscore], dtype=np.bool_),
    }


def split_window_dict(
    packed: Dict[str, np.ndarray],
    slices: Mapping[str, slice],
) -> Dict[str, Dict[str, np.ndarray]]:
    """Apply chronological slices to packed window arrays."""
    skip = {"per_window_zscore"}
    n = len(packed["x"])
    out: Dict[str, Dict[str, np.ndarray]] = {}
    for name, sl in slices.items():
        start = max(0, sl.start or 0)
        stop = min(n, sl.stop if sl.stop is not None else n)
        if stop <= start:
            raise ValueError(f"Empty {name} split after embargo")
        out[name] = {
            k: (v if k in skip else v[start:stop])
            for k, v in packed.items()
        }
    return out


def make_loader(
    packed: Dict[str, np.ndarray],
    *,
    y_path_z: np.ndarray,
    path_mask: np.ndarray,
    batch_size: int,
    shuffle: bool,
    per_window_zscore: bool,
) -> DataLoader:
    ds = NextCandleDataset(
        packed["x"],
        packed["x_cat"],
        y_path_z,
        path_mask,
        packed["volume_state"],
        packed["horizon_dirs"],
        packed["horizon_structs"],
        per_window_zscore=per_window_zscore,
    )
    return DataLoader(ds, batch_size=batch_size, shuffle=shuffle, drop_last=shuffle)


def classification_report_head(
    pred: np.ndarray,
    true: np.ndarray,
    *,
    name: str,
) -> Dict[str, float]:
    """Accuracy / balanced accuracy without requiring sklearn at import time."""
    pred = np.asarray(pred, dtype=np.int64)
    true = np.asarray(true, dtype=np.int64)
    mask = true >= 0
    pred = pred[mask]
    true = true[mask]
    if len(true) == 0:
        return {"name": name, "accuracy": 0.0, "balanced_accuracy": 0.0, "n": 0}
    acc = float((pred == true).mean())
    classes = np.unique(true)
    recalls = []
    for c in classes:
        denom = float((true == c).sum())
        if denom <= 0:
            continue
        recalls.append(float(((pred == c) & (true == c)).sum()) / denom)
    bal = float(np.mean(recalls)) if recalls else acc
    print(f"  {name:16s} acc={acc:.3f}  balanced={bal:.3f}  n={len(true)}")
    return {"name": name, "accuracy": acc, "balanced_accuracy": bal, "n": float(len(true))}


def _tensor_to_numpy(tensor: torch.Tensor) -> np.ndarray:
    """Convert without the torch–NumPy C-API (missing in some CPU wheels)."""
    return np.asarray(tensor.detach().cpu().tolist())


@torch.no_grad()
def evaluate_structure_heads(
    model: NextCandleTransformer,
    loader: DataLoader,
    *,
    device: torch.device,
) -> Dict[str, Any]:
    """Collect per-horizon direction accuracy and path-vol correlation."""
    model.eval()
    dir_pred: List[np.ndarray] = []
    dir_true: List[np.ndarray] = []
    path_pred: List[np.ndarray] = []
    path_true: List[np.ndarray] = []
    n_h = N_HORIZONS
    for batch in loader:
        xb, xcat = batch[0].to(device), batch[1].to(device)
        outs = model(xb, xcat)
        dirs = np.stack(
            [_tensor_to_numpy(outs[j].argmax(dim=1)) for j in range(n_h)],
            axis=1,
        )
        dir_pred.append(dirs)
        dir_true.append(_tensor_to_numpy(batch[5]))
        path_pred.append(_tensor_to_numpy(outs[2 * n_h]))
        path_true.append(_tensor_to_numpy(batch[2]))
    pred_d = np.concatenate(dir_pred, axis=0)
    true_d = np.concatenate(dir_true, axis=0)
    reports: Dict[str, Any] = {}
    for j, key in enumerate(HORIZON_KEYS):
        reports[f"{key}_dir"] = classification_report_head(
            pred_d[:, j], true_d[:, j], name=f"{key}_dir"
        )
    reports["direction"] = reports["h5m_dir"]
    pred_p = np.concatenate(path_pred, axis=0)
    true_p = np.concatenate(path_true, axis=0)
    vol_idx = [
        i for i, col in enumerate(V8_CONTINUOUS_LABEL_COLS) if col.endswith("_vol")
    ]
    corrs: List[float] = []
    for idx in vol_idx:
        a = pred_p[:, idx]
        b = true_p[:, idx]
        mask = np.isfinite(a) & np.isfinite(b)
        if int(mask.sum()) < 8:
            continue
        if float(np.std(a[mask])) < 1e-12 or float(np.std(b[mask])) < 1e-12:
            continue
        corrs.append(float(np.corrcoef(a[mask], b[mask])[0, 1]))
    reports["path_vol_corr"] = float(np.mean(corrs)) if corrs else 0.0
    print(f"  path_vol_corr={reports['path_vol_corr']:.3f}")
    return reports


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


def confusion_counts(pred: np.ndarray, true: np.ndarray, n_classes: int) -> np.ndarray:
    """Integer confusion matrix (rows=true, cols=pred)."""
    mat = np.zeros((n_classes, n_classes), dtype=np.int64)
    pred = np.asarray(pred, dtype=np.int64)
    true = np.asarray(true, dtype=np.int64)
    for t, p in zip(true, pred):
        if 0 <= t < n_classes and 0 <= p < n_classes:
            mat[t, p] += 1
    return mat


def pattern_context_table(df: pd.DataFrame) -> pd.DataFrame:
    """Named pattern × trend/volume vs subsequent 5m path_edge (analysis only)."""
    mfe_col = "h5m_mfe" if "h5m_mfe" in df.columns else "mfe"
    mae_col = "h5m_mae" if "h5m_mae" in df.columns else "mae"
    need = [
        c
        for c in (CHART_PATTERN_COL, "structure_bias", "vol_z", mfe_col, mae_col)
        if c in df.columns
    ]
    if len(need) < 3:
        return pd.DataFrame()
    work = df[need].copy()
    if mfe_col in work.columns and mae_col in work.columns:
        work["path_edge"] = work[mfe_col] - work[mae_col]
    grouped = work.groupby(CHART_PATTERN_COL, dropna=True).agg(
        n=(need[1], "count"),
        path_edge_mean=(
            "path_edge",
            "mean",
        )
        if "path_edge" in work.columns
        else (need[1], "mean"),
        structure_bias_mean=(
            "structure_bias",
            "mean",
        )
        if "structure_bias" in work.columns
        else (need[1], "mean"),
    )
    print(grouped.to_string())
    return grouped


def shap_grouped_stub(feature_cols: Sequence[str], *, enabled: bool) -> Dict[str, List[str]]:
    """Print grouped feature names for SHAP; skip computation unless enabled."""
    groups = {
        "candle": [c for c in feature_cols if c in (
            "body_ratio", "upper_wick_ratio", "lower_wick_ratio", "close_loc",
            "range_atr", "body_atr", "gap_atr", "inside_bar", "outside_bar",
        )],
        "trend": [c for c in feature_cols if "ema" in c or c in ("macd_hist", "adx_14", "rsi_14")],
        "structure": [c for c in feature_cols if c.startswith(("hh_", "hl_", "lh_", "ll_", "structure_"))],
        "chart_geometry": [c for c in feature_cols if c in (
            "peak_diff_atr", "trough_diff_atr", "flag_width_atr", CHART_PATTERN_COL,
        )],
        "vol": [c for c in feature_cols if c.startswith("rv_") or c == "atr"],
        "volume": [c for c in feature_cols if "vol" in c],
        "sr": [c for c in feature_cols if "support" in c or "resistance" in c],
        "multi_tf": [c for c in feature_cols if c.startswith("htf_")],
    }
    if not enabled:
        print("SHAP skipped (CONFIG run_shap=False). Feature groups:")
        for name, cols in groups.items():
            print(f"  {name}: {len(cols)} cols")
        return groups
    print("SHAP enabled — install shap in the Colab env and call shap.Explainer on a loader.")
    return groups


def optuna_search_stub(config: Mapping[str, Any]) -> Dict[str, Any]:
    """Optuna on walk-forward validation only. Never uses the final test split."""
    cfg = dict(config)
    if not cfg.get("run_optuna"):
        print("Optuna skipped (CONFIG run_optuna=False). Search space: sequence_length, lr, "
              "weight_decay, dropout, layers, heads, d_model, batch, loss lambdas.")
        return cfg
    try:
        import optuna  # noqa: F401
    except ImportError:
        print("Optuna not installed; leaving CONFIG unchanged.")
        return cfg
    print("Optuna enabled — objective must be walk-forward validation loss, never test.")
    return cfg


def run_walk_forward_eval(
    packed: Dict[str, np.ndarray],
    *,
    config: Mapping[str, Any],
    device: torch.device,
    y_mean: np.ndarray,
    y_std: np.ndarray,
    feature_index: Optional[np.ndarray] = None,
) -> List[float]:
    """One-epoch expanding-window direction accuracy (validation folds only)."""
    n = len(packed["x"])
    embargo = max(1, int(config.get("walk_forward_embargo") or 1))
    scores: List[float] = []
    for train_sl, val_sl in walk_forward_slices(
        n, folds=int(config.get("walk_forward_folds") or 3), embargo=embargo
    ):
        tr = {k: (v[train_sl] if k != "per_window_zscore" else v) for k, v in packed.items()}
        va = {k: (v[val_sl] if k != "per_window_zscore" else v) for k, v in packed.items()}
        if feature_index is not None:
            tr["x"] = tr["x"][:, :, feature_index]
            va["x"] = va["x"][:, :, feature_index]
        if len(tr["x"]) < 4 or len(va["x"]) < 2:
            continue
        scores.append(
            run_ablation_epoch(
                tr, va, feature_index=np.arange(tr["x"].shape[-1]),
                config=config, device=device, y_mean=y_mean, y_std=y_std,
            )
        )
    print(f"Walk-forward val direction acc: {scores}")
    return scores


def run_ablation_epoch(
    packed_train: Dict[str, np.ndarray],
    packed_val: Dict[str, np.ndarray],
    *,
    feature_index: np.ndarray,
    config: Mapping[str, Any],
    device: torch.device,
    y_mean: np.ndarray,
    y_std: np.ndarray,
) -> float:
    """Single-epoch ablation on a feature subset; returns val direction accuracy."""
    def _sub(p: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
        q = dict(p)
        q["x"] = p["x"][:, :, feature_index]
        return q

    tr = _sub(packed_train)
    va = _sub(packed_val)
    ytr_z, mtr = standardize_labels(tr["y_path"], y_mean, y_std)
    yva_z, mva = standardize_labels(va["y_path"], y_mean, y_std)
    model = NextCandleTransformer(
        n_features=int(tr["x"].shape[-1]),
        d_model=32,
        nhead=4,
        num_layers=1,
        dropout=0.1,
        max_len=int(config.get("sequence_length") or 64),
        n_continuous=len(V8_CONTINUOUS_LABEL_COLS),
    ).to(device)
    loader_tr = make_loader(
        tr,
        y_path_z=ytr_z,
        path_mask=mtr,
        batch_size=min(64, len(tr["x"])),
        shuffle=True,
        per_window_zscore=False,
    )
    loader_va = make_loader(
        va,
        y_path_z=yva_z,
        path_mask=mva,
        batch_size=min(64, max(len(va["x"]), 1)),
        shuffle=False,
        per_window_zscore=False,
    )
    train_next_candle(
        model,
        loader_tr,
        loader_va,
        device=device,
        epochs=1,
        lr=1e-3,
        weight_decay=1e-4,
        patience=1,
        loss_weights=config.get("loss_weights"),
    )
    metrics = evaluate_structure_heads(model, loader_va, device=device)
    return float(metrics["direction"]["accuracy"])


def export_v8_bundle(
    model: NextCandleTransformer,
    export_dir: Path,
    *,
    device: torch.device,
    window_len: int,
    n_features: int,
    feature_cols: Sequence[str],
    label_mean: np.ndarray,
    label_std: np.ndarray,
    config: Mapping[str, Any],
    scaler_mean: Optional[np.ndarray] = None,
    scaler_std: Optional[np.ndarray] = None,
) -> Tuple[Path, Path, Path]:
    """Write ONNX + feature_config.json + metadata_transformer.json (v8)."""
    export_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = export_dir / "btcusd_5m_transformer.onnx"
    dummy_x = torch.zeros(1, window_len, n_features, device=device)
    dummy_c = torch.zeros(1, window_len, dtype=torch.long, device=device)
    model.eval()
    output_names = list(ONNX_OUTPUT_NAMES_V8)
    torch.onnx.export(
        model,
        (dummy_x, dummy_c),
        str(onnx_path),
        input_names=["continuous_features", "candle_class_ids"],
        output_names=output_names,
        dynamic_axes={
            "continuous_features": {0: "batch"},
            "candle_class_ids": {0: "batch"},
            **{name: {0: "batch"} for name in output_names},
        },
        opset_version=17,
        dynamo=False,
    )
    cfg = dict(config)
    feature_config = feature_config_from_training_export(
        feature_cols=feature_cols,
        window_len=window_len,
        label_mean=label_mean,
        label_std=label_std,
        q_edges=[0.25, 0.5, 0.75],
        config=cfg,
        contract_version=FEATURE_CONTRACT_VERSION,
        onnx_output_names=output_names,
        continuous_label_cols=V8_CONTINUOUS_LABEL_COLS,
    )
    if scaler_mean is not None and scaler_std is not None:
        feature_config["scaler_mean"] = [float(x) for x in scaler_mean]
        feature_config["scaler_std"] = [float(x) for x in scaler_std]
        feature_config["scaler_mode"] = "train_fit"
    cfg_path = export_dir / "feature_config.json"
    cfg_path.write_text(json.dumps(feature_config, indent=2), encoding="utf-8")
    meta = metadata_from_training_export(
        resolution="5m",
        label_mean=label_mean,
        label_std=label_std,
        config=cfg,
        onnx_output_names=output_names,
    )
    meta_path = export_dir / "metadata_transformer.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return onnx_path, cfg_path, meta_path


def export_v7_bundle(
    model: NextCandleTransformer,
    export_dir: Path,
    *,
    device: torch.device,
    window_len: int,
    n_features: int,
    feature_cols: Sequence[str],
    label_mean: np.ndarray,
    label_std: np.ndarray,
    config: Mapping[str, Any],
    scaler_mean: Optional[np.ndarray] = None,
    scaler_std: Optional[np.ndarray] = None,
) -> Tuple[Path, Path, Path]:
    """Alias for notebook/smoke compatibility."""
    return export_v8_bundle(
        model,
        export_dir,
        device=device,
        window_len=window_len,
        n_features=n_features,
        feature_cols=feature_cols,
        label_mean=label_mean,
        label_std=label_std,
        config=config,
        scaler_mean=scaler_mean,
        scaler_std=scaler_std,
    )


def run_research_training(
    raw_5m: pd.DataFrame,
    *,
    export_dir: Path,
    config: Optional[Mapping[str, Any]] = None,
    funding_df: Optional[pd.DataFrame] = None,
    oi_df: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """End-to-end research train on a 5m OHLCV frame (immutable)."""
    cfg = default_research_config()
    if config:
        cfg.update(dict(config))
    set_research_seed(int(cfg["seed"]))
    assembled = assemble_raw_frame(raw_5m, funding_df=funding_df, oi_df=oi_df)
    ohlcv_quality_report(assembled, "5m", symbol=str(cfg.get("symbol") or "BTCUSD"))
    labeled = build_labeled_frame(assembled, config=cfg)
    feature_cols = list(v8_feature_cols_for_resolution("5m"))
    feature_cols = [c for c in feature_cols if c in labeled.columns]
    leakage_audit(feature_cols)

    window_len = int(cfg["sequence_length"])
    stride = int(cfg.get("stride") or 4)
    n = len(labeled)
    embargo = int(
        cfg.get("embargo_bars")
        or cfg.get("path_label_horizon_bars")
        or MAX_V8_HORIZON_BARS
    )
    slices = chronological_split(
        n,
        train_ratio=float(cfg["train_ratio"]),
        validation_ratio=float(cfg["validation_ratio"]),
        embargo=embargo,
    )
    train_df = labeled.iloc[slices["train"]].reset_index(drop=True)
    train_x = train_df[feature_cols].to_numpy(dtype=np.float64)
    feature_finite_report(train_x, feature_cols)
    scaler_mean, scaler_std = fit_train_scaler(train_x)
    per_window = str(cfg.get("scaler_mode") or "train_fit") == "per_window"
    packed_all = windows_from_frame(
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
        train_ratio=float(cfg["train_ratio"]),
        validation_ratio=float(cfg["validation_ratio"]),
        embargo=max(1, min(4, embargo // max(stride, 1))),
    )
    splits = split_window_dict(packed_all, win_slices)
    y_mean, y_std = fit_label_stats(splits["train"]["y_path"])
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"device: {device}  windows train/val/test="
          f"{len(splits['train']['x'])}/{len(splits['val']['x'])}/{len(splits['test']['x'])}")

    loaders = {}
    for name, shuffle in (("train", True), ("val", False), ("test", False)):
        yz, mask = standardize_labels(splits[name]["y_path"], y_mean, y_std)
        loaders[name] = make_loader(
            splits[name],
            y_path_z=yz,
            path_mask=mask,
            batch_size=int(cfg["batch_size"]),
            shuffle=shuffle,
            per_window_zscore=per_window,
        )

    model = NextCandleTransformer(
        n_features=len(feature_cols),
        d_model=int(cfg.get("d_model") or 64),
        nhead=int(cfg.get("nhead") or 4),
        num_layers=int(cfg.get("num_layers") or 2),
        dropout=float(cfg["dropout"]),
        max_len=window_len,
        n_continuous=len(V8_CONTINUOUS_LABEL_COLS),
    ).to(device)
    train_hist = train_next_candle(
        model,
        loaders["train"],
        loaders["val"],
        device=device,
        epochs=int(cfg["epochs"]),
        lr=float(cfg["learning_rate"]),
        weight_decay=float(cfg["weight_decay"]),
        patience=int(cfg["early_stopping_patience"]),
        loss_weights=cfg.get("loss_weights"),
    )
    if not train_hist.get("ok"):
        raise RuntimeError(f"Training aborted with non-finite loss: {train_hist}")
    print("Validation:")
    val_metrics = evaluate_structure_heads(model, loaders["val"], device=device)
    print("Test (untouched):")
    test_metrics = evaluate_structure_heads(model, loaders["test"], device=device)

    if cfg.get("run_ablations"):
        groups = ablation_feature_groups("5m")
        print("Ablation direction accuracy (val, 1 epoch):")
        for key, cols in groups.items():
            idx = np.array(
                [feature_cols.index(c) for c in cols if c in feature_cols],
                dtype=np.int64,
            )
            if len(idx) < 3:
                continue
            acc = run_ablation_epoch(
                splits["train"],
                splits["val"],
                feature_index=idx,
                config=cfg,
                device=device,
                y_mean=y_mean,
                y_std=y_std,
            )
            print(f"  {key}: {acc:.3f}  n_features={len(idx)}")

    onnx_path, cfg_path, meta_path = export_v8_bundle(
        model,
        export_dir,
        device=device,
        window_len=window_len,
        n_features=len(feature_cols),
        feature_cols=feature_cols,
        label_mean=y_mean,
        label_std=y_std,
        config=cfg,
        scaler_mean=None if per_window else scaler_mean,
        scaler_std=None if per_window else scaler_std,
    )
    return {
        "val_metrics": val_metrics,
        "test_metrics": test_metrics,
        "onnx": str(onnx_path),
        "feature_config": str(cfg_path),
        "metadata": str(meta_path),
        "n_features": len(feature_cols),
        "chart_pattern_col": CHART_PATTERN_COL,
    }


def fetch_and_train(
    *,
    export_dir: Path,
    cache_dir: Path,
    config: Optional[Mapping[str, Any]] = None,
    refresh_data: bool = False,
) -> Dict[str, Any]:
    """Fetch 5m history from Delta India (cached) and run research training."""
    cfg = default_research_config()
    if config:
        cfg.update(dict(config))
    cache_dir.mkdir(parents=True, exist_ok=True)
    parquet = cache_dir / "btcusd_5m_raw.parquet"
    if parquet.is_file() and not refresh_data:
        raw = pd.read_parquet(parquet)
    else:
        raw = fetch_history_bundle(
            symbol=str(cfg["symbol"]),
            resolution="5m",
            history_days=int(cfg.get("history_days") or 900),
            base_url=str(cfg.get("base_url") or "https://api.india.delta.exchange"),
        )
        parquet.parent.mkdir(parents=True, exist_ok=True)
        raw.to_parquet(parquet, index=False)
    return run_research_training(raw, export_dir=export_dir, config=cfg)
