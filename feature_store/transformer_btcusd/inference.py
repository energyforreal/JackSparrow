"""Window building and label un-standardization for per-TF transformer inference."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence, Tuple

import numpy as np

from feature_store.transformer_btcusd.contract import (
    CANDLE_CLASS_CARDINALITY,
    CANDLE_CLASS_COL,
    CANDLE_CLASS_NAMES,
    CONTINUOUS_LABEL_COLS,
    FEATURE_COLS,
    FEATURE_CONTRACT_VERSION,
    FEATURE_CONTRACT_VERSION_V6,
    FEATURE_CONTRACT_VERSION_V7,
    ONNX_OUTPUT_NAMES,
    ONNX_OUTPUT_NAMES_V6,
    ONNX_OUTPUT_NAMES_V7,
    ONNX_OUTPUT_NAMES_V8,
    STRUCTURE_OUTCOME_NAMES,
    TRANSFORMER_FEATURE_CONFIG_FILENAME,
    V8_CONTINUOUS_LABEL_COLS,
    default_training_config,
    model_family_for_resolution,
    onnx_filename_for_resolution,
    onnx_output_names_for_contract,
)


def load_feature_config(path: Path) -> Dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return raw


def resolve_feature_config(bundle_dir: Path) -> Dict[str, Any]:
    cfg_path = bundle_dir / TRANSFORMER_FEATURE_CONFIG_FILENAME
    if not cfg_path.is_file():
        raise FileNotFoundError(
            f"Missing {TRANSFORMER_FEATURE_CONFIG_FILENAME} in {bundle_dir}"
        )
    return load_feature_config(cfg_path)


def zscore_window(window: np.ndarray) -> np.ndarray:
    """Per-window z-score (matches Colab WindowDataset)."""
    mu = window.mean(axis=0, keepdims=True)
    sd = window.std(axis=0, keepdims=True) + 1e-6
    return ((window - mu) / sd).astype(np.float32)


def build_continuous_window(
    feat_values: np.ndarray,
    *,
    window_len: int,
    feature_cols: Sequence[str] = FEATURE_COLS,
) -> np.ndarray:
    """Build a z-scored (1, window_len, n_features) tensor from continuous cols."""
    if feat_values.shape[0] < window_len:
        raise ValueError(
            f"Need at least {window_len} feature rows, got {feat_values.shape[0]}"
        )
    window = feat_values[-window_len:, :].astype(np.float32)
    if not np.isfinite(window).all():
        raise ValueError("Feature window contains non-finite values")
    normed = zscore_window(window)
    return normed[np.newaxis, :, :]


def build_candle_class_window(
    class_ids: np.ndarray,
    *,
    window_len: int,
    max_class_id: int = CANDLE_CLASS_CARDINALITY - 1,
) -> np.ndarray:
    """Build a raw (1, window_len) int64 tensor of candle class ids."""
    ids = np.asarray(class_ids).reshape(-1)
    if ids.shape[0] < window_len:
        raise ValueError(
            f"Need at least {window_len} candle class rows, got {ids.shape[0]}"
        )
    window = ids[-window_len:].astype(np.int64)
    if np.any((window < 0) | (window > max_class_id)):
        raise ValueError(
            f"{CANDLE_CLASS_COL} out of range [0, {max_class_id}]"
        )
    return window[np.newaxis, :]


def build_inference_window(
    feat_values: np.ndarray,
    *,
    window_len: int,
    feature_cols: Sequence[str] = FEATURE_COLS,
) -> np.ndarray:
    """Build a single (1, window_len, n_features) tensor from feature matrix values."""
    return build_continuous_window(
        feat_values, window_len=window_len, feature_cols=feature_cols
    )


def unstandardize_continuous(
    pred_z: np.ndarray,
    label_mean: Sequence[float],
    label_std: Sequence[float],
    *,
    label_cols: Sequence[str] = CONTINUOUS_LABEL_COLS,
) -> Dict[str, float]:
    """Map standardized ONNX output back to real units."""
    mean = np.asarray(label_mean, dtype=np.float64)
    std = np.asarray(label_std, dtype=np.float64)
    flat = np.asarray(pred_z, dtype=np.float64).reshape(-1)
    if flat.shape[0] != len(label_cols):
        raise ValueError(
            f"Expected {len(label_cols)} continuous outputs, got {flat.shape[0]}"
        )
    real = flat * std + mean
    return {str(col): float(val) for col, val in zip(label_cols, real)}


def softmax(logits: np.ndarray) -> np.ndarray:
    x = np.asarray(logits, dtype=np.float64).reshape(-1)
    x = x - x.max()
    exp = np.exp(x)
    return exp / (exp.sum() + 1e-12)


def parse_regime_prediction(
    regime_logits: np.ndarray,
    regime_names: Mapping[str, str],
) -> Tuple[int, str, Dict[str, float]]:
    probs = softmax(regime_logits)
    idx = int(np.argmax(probs))
    name = regime_names.get(str(idx), regime_names.get(idx, f"CLASS_{idx}"))
    prob_map = {
        regime_names.get(str(i), f"CLASS_{i}"): float(probs[i])
        for i in range(len(probs))
    }
    return idx, str(name), prob_map


def require_onnx_output_names(
    output_names: Sequence[str],
    *,
    contract_version: str | None = None,
    resolution: str = "15m",
) -> None:
    """Reject bundles that lack the heads required by the given contract."""
    have = {str(name) for name in output_names}
    ver = str(contract_version or FEATURE_CONTRACT_VERSION_V6)
    required = onnx_output_names_for_contract(ver, resolution=resolution)
    known = (
        FEATURE_CONTRACT_VERSION,
        FEATURE_CONTRACT_VERSION_V7,
        FEATURE_CONTRACT_VERSION_V6,
    )
    if ver not in known and not required:
        required = ONNX_OUTPUT_NAMES_V6
    missing = [name for name in required if name not in have]
    if missing:
        raise RuntimeError(
            f"ONNX bundle is not {ver}: missing outputs {missing}. Retrain all TFs."
        )


def feature_config_from_training_export(
    *,
    feature_cols: Sequence[str],
    window_len: int,
    label_mean: Sequence[float],
    label_std: Sequence[float],
    q_edges: Sequence[float],
    config: Mapping[str, Any],
    contract_version: str | None = None,
    onnx_output_names: Sequence[str] | None = None,
    continuous_label_cols: Sequence[str] | None = None,
) -> Dict[str, Any]:
    """Build feature_config.json payload written by Colab export cell."""
    version = str(contract_version or FEATURE_CONTRACT_VERSION_V6)
    if onnx_output_names is not None:
        names = list(onnx_output_names)
    elif version == FEATURE_CONTRACT_VERSION:
        names = list(ONNX_OUTPUT_NAMES_V8)
    elif version == FEATURE_CONTRACT_VERSION_V7:
        names = list(ONNX_OUTPUT_NAMES_V7)
    else:
        names = list(ONNX_OUTPUT_NAMES)
    if continuous_label_cols is not None:
        label_cols = list(continuous_label_cols)
    elif version == FEATURE_CONTRACT_VERSION:
        label_cols = list(V8_CONTINUOUS_LABEL_COLS)
    else:
        label_cols = list(CONTINUOUS_LABEL_COLS)
    return {
        "feature_contract_version": version,
        "feature_cols": list(feature_cols),
        "categorical_cols": [CANDLE_CLASS_COL],
        "categorical_cardinality": {CANDLE_CLASS_COL: CANDLE_CLASS_CARDINALITY},
        "candle_class_names": {str(k): v for k, v in CANDLE_CLASS_NAMES.items()},
        "window_len": int(window_len),
        "continuous_label_cols": label_cols,
        "label_mean": [float(x) for x in label_mean],
        "label_std": [float(x) for x in label_std],
        "regime_names": {"0": "LOW", "1": "NORMAL", "2": "HIGH", "3": "EXTREME"},
        "structure_outcome_names": {
            str(k): v for k, v in STRUCTURE_OUTCOME_NAMES.items()
        },
        "onnx_output_names": names,
        "vol_regime_quantile_edges": [float(x) for x in q_edges],
        "config": dict(config),
    }


def metadata_from_training_export(
    *,
    resolution: str,
    label_mean: Sequence[float],
    label_std: Sequence[float],
    config: Mapping[str, Any],
    test_metrics: Mapping[str, Any] | None = None,
    export_quality: Mapping[str, Any] | None = None,
    onnx_output_names: Sequence[str] | None = None,
) -> Dict[str, Any]:
    """Build metadata_transformer.json for a per-TF bundle."""
    res = resolution.strip().lower()
    cfg = dict(config)
    names = list(onnx_output_names or ONNX_OUTPUT_NAMES)
    meta: Dict[str, Any] = {
        "version": "transformer_per_tf_v1",
        "model_name": f"jacksparrow_transformer_BTCUSD_{res}",
        "model_family": model_family_for_resolution(res),
        "symbol": str(cfg.get("symbol") or "BTCUSD"),
        "resolution": res,
        "resolution_minutes": int(cfg.get("resolution_minutes") or 15),
        "onnx_filename": onnx_filename_for_resolution(res),
        "feature_config_filename": TRANSFORMER_FEATURE_CONFIG_FILENAME,
        "path_label_horizon_bars": int(cfg.get("path_label_horizon_bars") or 8),
        "atr_period": int(cfg.get("atr_period") or 14),
        "default_threshold": float(cfg.get("default_threshold") or 0.005),
        "primary_signal_mode": "path_edge",
        "onnx_output_names": names,
        "label_mean": [float(x) for x in label_mean],
        "label_std": [float(x) for x in label_std],
        "test_metrics": dict(test_metrics or {}),
        "training_config": cfg,
    }
    if export_quality:
        meta["export_quality"] = dict(export_quality)
    return meta


def training_config_for_resolution(resolution: str) -> Dict[str, Any]:
    return default_training_config(resolution)
